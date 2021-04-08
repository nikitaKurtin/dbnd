import attr


@attr.s
class LastSeenValues:
    last_seen_dag_run_id = attr.ib()  # type: Optional[int]
    last_seen_log_id = attr.ib()  # type: Optional[int]

    def as_dict(self):
        return dict(
            last_seen_dag_run_id=self.last_seen_dag_run_id,
            last_seen_log_id=self.last_seen_log_id,
        )

    @classmethod
    def from_dict(cls, data):
        return cls(
            last_seen_dag_run_id=data.get("last_seen_dag_run_id"),
            last_seen_log_id=data.get("last_seen_log_id"),
        )


@attr.s
class AirflowDagRun:
    id = attr.ib()  # type: int
    dag_id = attr.ib()  # type: str
    execution_date = attr.ib()  # type: str
    state = attr.ib()  # type: str
    is_paused = attr.ib()  # type: bool
    has_updated_task_instances = attr.ib()  # type: bool
    max_log_id = attr.ib()  # type: int
    events = attr.ib(default=None)  # type: str


@attr.s
class AirflowDagRunsResponse:
    dag_runs = attr.ib()  # type: List[AirflowDagRun]
    last_seen_dag_run_id = attr.ib()  # type: Optional[int]
    last_seen_log_id = attr.ib()  # type: Optional[int]

    @classmethod
    def from_dict(cls, data):
        return cls(
            dag_runs=[
                AirflowDagRun(
                    id=dr.get("id"),
                    dag_id=dr.get("dag_id"),
                    execution_date=dr.get("execution_date"),
                    state=dr.get("state"),
                    is_paused=dr.get("is_paused"),
                    has_updated_task_instances=dr.get("has_updated_task_instances"),
                    max_log_id=dr.get("max_log_id"),
                )
                for dr in data.get("new_dag_runs")
            ],
            last_seen_dag_run_id=data.get("last_seen_dag_run_id"),
            last_seen_log_id=data.get("last_seen_log_id"),
        )


@attr.s
class DagRunsFullData:
    dags = attr.ib()
    dag_runs = attr.ib()
    task_instances = attr.ib()

    def as_dict(self):
        return dict(
            dags=self.dags, dag_runs=self.dag_runs, task_instances=self.task_instances
        )

    @classmethod
    def from_dict(cls, data):
        return cls(
            dags=[dag for dag in data.get("dags")],
            dag_runs=[dag_run for dag_run in data.get("dag_runs")],
            task_instances=[
                task_instance for task_instance in data.get("task_instances")
            ],
        )


@attr.s
class DagRunsStateData:
    dag_runs = attr.ib()
    task_instances = attr.ib()

    def as_dict(self):
        return dict(task_instances=self.task_instances, dag_runs=self.dag_runs)

    @classmethod
    def from_dict(cls, data):
        return cls(
            task_instances=[
                task_instance for task_instance in data.get("task_instances")
            ],
            dag_runs=[dag_run for dag_run in data.get("dag_runs")],
        )