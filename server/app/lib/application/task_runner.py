from . import task_factory


def run_typo_correction(*, request: str, batch_mode: bool = True, **workflow_kwargs):
	workflow = task_factory.create_typo_workflow(**workflow_kwargs)
	return workflow.run(request, batch_mode=batch_mode)
