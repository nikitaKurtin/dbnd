# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging
import signal

from airflow.contrib.executors.kubernetes_executor import (
    AirflowKubernetesScheduler,
    KubeConfig,
    KubernetesExecutor,
    KubernetesJobWatcher,
)
from airflow.models import KubeWorkerIdentifier
from airflow.utils.db import provide_session
from airflow.utils.state import State

from dbnd._core.current import try_get_databand_run
from dbnd._core.task_build.task_registry import build_task_from_config
from dbnd_docker.kubernetes.kube_dbnd_client import DbndKubernetesClient
from dbnd_docker.kubernetes.kubernetes_engine_config import KubernetesEngineConfig

MAX_POD_ID_LEN = 253

logger = logging.getLogger(__name__)


def _update_airflow_kube_config(airflow_kube_config, engine_config):
    # type:( KubeConfig, KubernetesEngineConfig) -> None
    # We (almost) don't need this mapping any more
    # Pod is created using  databand KubeConfig
    # We still are mapping databand KubeConfig -> airflow KubeConfig as some functions are using values from it.
    ec = engine_config

    secrets = ec.get_secrets()
    if secrets:
        kube_secrets = {}
        env_from_secret_ref = []
        for s in secrets:
            if s.deploy_type == "env":
                if s.deploy_target:
                    kube_secrets[s.deploy_target] = "%s=%s" % (s.secret, s.key)
                else:
                    env_from_secret_ref.append(s.secret)

        if kube_secrets:
            airflow_kube_config.kube_secrets.update(kube_secrets)

        if env_from_secret_ref:
            airflow_kube_config.env_from_secret_ref = ",".join(env_from_secret_ref)

    if ec.env_vars is not None:
        airflow_kube_config.kube_env_vars.update(ec.env_vars)

    if ec.configmaps is not None:
        airflow_kube_config.env_from_configmap_ref = ",".join(ec.configmaps)

    if ec.container_repository is not None:
        airflow_kube_config.worker_container_repository = ec.container_repository
    if ec.container_tag is not None:
        airflow_kube_config.worker_container_tag = ec.container_tag
    airflow_kube_config.kube_image = "{}:{}".format(
        airflow_kube_config.worker_container_repository,
        airflow_kube_config.worker_container_tag,
    )

    if ec.image_pull_policy is not None:
        airflow_kube_config.kube_image_pull_policy = ec.image_pull_policy
    if ec.node_selectors is not None:
        airflow_kube_config.kube_node_selectors.update(ec.node_selectors)
    if ec.annotations is not None:
        airflow_kube_config.kube_annotations.update(ec.annotations)

    if ec.pods_creation_batch_size is not None:
        airflow_kube_config.worker_pods_creation_batch_size = (
            ec.pods_creation_batch_size
        )
    if ec.service_account_name is not None:
        airflow_kube_config.worker_service_account_name = ec.service_account_name
    if ec.image_pull_secrets is not None:
        airflow_kube_config.image_pull_secrets = ec.image_pull_secrets

    if ec.namespace is not None:
        airflow_kube_config.kube_namespace = ec.namespace
    if ec.namespace is not None:
        airflow_kube_config.executor_namespace = ec.namespace

    if ec.gcp_service_account_keys is not None:
        airflow_kube_config.gcp_service_account_keys = ec.gcp_service_account_keys
    if ec.affinity is not None:
        airflow_kube_config.kube_affinity = ec.affinity
    if ec.tolerations is not None:
        airflow_kube_config.kube_tolerations = ec.tolerations


class DbndKubernetesScheduler(AirflowKubernetesScheduler):
    def __init__(
        self, kube_config, task_queue, result_queue, kube_client, worker_uuid, kube_dbnd
    ):
        super(DbndKubernetesScheduler, self).__init__(
            kube_config, task_queue, result_queue, kube_client, worker_uuid
        )
        self.kube_dbnd = kube_dbnd

        # PATCH manage watcher
        from multiprocessing.managers import SyncManager

        self._manager = SyncManager()
        self._manager.start(mgr_init)

        self.watcher_queue = self._manager.Queue()
        self.current_resource_version = 0
        self.kube_watcher = self._make_kube_watcher_dbnd()
        # will be used to low level pod interactions
        self.running_pods = {}


    def _make_kube_watcher(self):
        # prevent storing in db of the kubernetes resource version, because the kubernetes db model only stores a single value
        # of the resource version while we need to store a sperate value for every kubernetes executor (because even in a basic flow
        # we can have two Kubernets executors running at once, the one that launched the driver and the one inside the driver).
        #
        # the resource version is the position inside the event stream of the kubernetes cluster and is used by the watcher to poll
        # Kubernets for events. It's probably fine to not store this because by default Kubernetes will returns "the evens currently in cache"
        # https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/CoreV1Api.md#list_namespaced_pod
        return None

    def _make_kube_watcher_dbnd(self):
        watcher = DbndKubernetesJobWatcher(
            namespace=self.namespace,
            watcher_queue=self.watcher_queue,
            resource_version=self.current_resource_version,
            worker_uuid=self.worker_uuid,
            kube_config=self.kube_config,
            kube_dbnd=self.kube_dbnd,
        )
        watcher.start()
        return watcher

    @staticmethod
    def _create_pod_id(dag_id, task_id):
        task_run = try_get_databand_run().get_task_run(task_id)
        return task_run.job_id__dns1123

    def _health_check_kube_watcher(self):
        if self.kube_watcher.is_alive():
            pass
        else:
            self.log.error(
                "Error while health checking kube watcher process. "
                "Process died for unknown reasons"
            )
            self.kube_watcher = self._make_kube_watcher_dbnd()

    def run_next(self, next_job):
        """

        The run_next command will check the task_queue for any un-run jobs.
        It will then create a unique job-id, launch that job in the cluster,
        and store relevant info in the current_jobs map so we can track the job's
        status
        """
        key, command, kube_executor_config = next_job
        dag_id, task_id, execution_date, try_number = key
        self.log.debug(
            "Kube POD to submit: image=%s with %s",
            self.kube_config.kube_image,
            str(next_job),
        )

        dr = try_get_databand_run()
        task_run = dr.get_task_run_by_af_id(task_id)
        pod_command = [str(c) for c in command]
        with task_run.runner.task_run_driver_context():
            kubernetes_config = build_task_from_config(
                task_name=self.kube_dbnd.engine_config.task_name
            )  # type: KubernetesEngineConfig
        pod = kubernetes_config.build_pod(
            task_run=task_run,
            cmds=pod_command,
            labels={
                "airflow-worker": self.worker_uuid,
                "dag_id": self._make_safe_label_value(dag_id),
                "task_id": self._make_safe_label_value(task_run.task_af_id),
                "execution_date": self._datetime_to_label_safe_datestring(
                    execution_date
                ),
                "try_number": str(try_number),
            },
        )

        pod_ctrl = self.kube_dbnd.get_pod_ctrl_for_pod(pod)
        self.running_pods[pod.name] = self.namespace
        pod_ctrl.run_pod(pod=pod, task_run=task_run, detach_run=True)

    def delete_pod(self, pod_id):
        self.running_pods.pop(pod_id, None)
        return self.kube_dbnd.delete_pod(pod_id, self.namespace)

    def terminate(self):

        logger.info("Deleting submitted pods: %s" % self.running_pods)
        for pod_name in list(self.running_pods.keys()):
            try:
                self.delete_pod(pod_name)
            except Exception:
                logger.exception("Failed to terminate pod %s", pod_name)
        super(DbndKubernetesScheduler, self).terminate()

def mgr_sig_handler(signal, frame):
    logger.error("Kubernetes python SyncManager got SIGINT (waiting for .stop command)")


def mgr_init():
    signal.signal(signal.SIGINT, mgr_sig_handler)


class DbndKubernetesExecutor(KubernetesExecutor):
    def __init__(self, kube_dbnd=None):
        # type: (DbndKubernetesExecutor, DbndKubernetesClient) -> None
        super(DbndKubernetesExecutor, self).__init__()

        from multiprocessing.managers import SyncManager

        self._manager = SyncManager()

        self.kube_dbnd = kube_dbnd
        _update_airflow_kube_config(
            airflow_kube_config=self.kube_config, engine_config=kube_dbnd.engine_config
        )

    def start(self):
        logger.info("Starting Kubernetes executor..")
        self._manager.start(mgr_init)

        dbnd_run = try_get_databand_run()
        if dbnd_run:
            self.worker_uuid = str(dbnd_run.run_uid)
        else:
            self.worker_uuid = (
                KubeWorkerIdentifier.get_or_create_current_kube_worker_uuid()
            )
        self.log.debug("Start with worker_uuid: %s", self.worker_uuid)

        # always need to reset resource version since we don't know
        # when we last started, note for behavior below
        # https://github.com/kubernetes-client/python/blob/master/kubernetes/docs
        # /CoreV1Api.md#list_namespaced_pod
        # KubeResourceVersion.reset_resource_version()
        self.task_queue = self._manager.Queue()
        self.result_queue = self._manager.Queue()

        self.kube_client = self.kube_dbnd.kube_client
        self.kube_scheduler = DbndKubernetesScheduler(
            self.kube_config,
            self.task_queue,
            self.result_queue,
            self.kube_client,
            self.worker_uuid,
            kube_dbnd=self.kube_dbnd,
        )

        if self.kube_dbnd.engine_config.debug:
            self.log.setLevel(logging.DEBUG)
            self.kube_scheduler.log.setLevel(logging.DEBUG)

        self._inject_secrets()
        self.clear_not_launched_queued_tasks()
        self._flush_result_queue()

    # override - by default UpdateQuery not working failing with
    # sqlalchemy.exc.CompileError: Unconsumed column names: state
    # due to model override
    # + we don't want to change tasks statuses - maybe they are managed by other executors
    @provide_session
    def clear_not_launched_queued_tasks(self, *args, **kwargs):
        # we don't clear kubernetes tasks from previous run
        pass


class DbndKubernetesJobWatcher(KubernetesJobWatcher):
    def __init__(self, kube_dbnd, **kwargs):
        super(DbndKubernetesJobWatcher, self).__init__(**kwargs)
        self.kube_dbnd = kube_dbnd

    def run(self):
        try:
            super(DbndKubernetesJobWatcher, self).run()
        except KeyboardInterrupt:
            # because we convert SIGTERM to SIGINT without this you get an ugly exception in the log when
            # the executor terminates the watcher
            pass

    def _run(self, kube_client, resource_version, worker_uuid, kube_config):
        self.log.info(
            "Event: and now my watch begins starting at resource_version: %s",
            resource_version,
        )

        from kubernetes import watch

        watcher = watch.Watch()

        kwargs = {"label_selector": "airflow-worker={}".format(worker_uuid)}
        if resource_version:
            kwargs["resource_version"] = resource_version
        if kube_config.kube_client_request_args:
            for key, value in kube_config.kube_client_request_args.items():
                kwargs[key] = value

        last_resource_version = None
        for event in watcher.stream(
            kube_client.list_namespaced_pod, self.namespace, **kwargs
        ):
            # DBND PATCH
            # we want to process the message
            task = event["object"]
            self.log.debug(
                "Event: %s had an event of type %s", task.metadata.name, event["type"]
            )

            if event["type"] == "ERROR":
                return self.process_error(event)
            status = self.kube_dbnd.process_pod_event(event)

            self.process_status_quite(
                task.metadata.name,
                status,
                task.metadata.labels,
                task.metadata.resource_version,
            )
            last_resource_version = task.metadata.resource_version

        return last_resource_version

    def process_status_quite(self, pod_id, status, labels, resource_version):
        """Process status response"""
        if status == "Pending":
            self.log.debug("Event: %s Pending", pod_id)
        elif status == "Failed":
            self.log.debug("Event: %s Failed", pod_id)
            self.watcher_queue.put((pod_id, State.FAILED, labels, resource_version))
        elif status == "Succeeded":
            self.log.debug("Event: %s Succeeded", pod_id)
            self.watcher_queue.put((pod_id, None, labels, resource_version))
        elif status == "Running":
            self.log.debug("Event: %s is Running", pod_id)
        else:
            self.log.warning(
                "Event: Invalid state: %s on pod: %s with labels: %s with "
                "resource_version: %s",
                status,
                pod_id,
                labels,
                resource_version,
            )
