from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed


def parallel_map(
	func: Callable,
	iterable: Sequence,
	max_workers: int = 20,
	iterable_kwargs: Sequence[dict] | None = None,
	*args,
	**kwargs
) -> list:
	"""
	Execute a function over a sequence in parallel using a thread pool.
	Returns results in the same order as the input sequence.
	"""
	# zip() would silently truncate to the shorter of the two and leave the
	# unsubmitted tail of results as None, which surfaces far from here as an
	# AttributeError on the caller's side.
	if iterable_kwargs is not None and len(iterable_kwargs) != len(iterable):
		raise ValueError(
			f"iterable_kwargs has {len(iterable_kwargs)} entries but iterable has {len(iterable)}"
		)

	results = [None] * len(iterable)
	with ThreadPoolExecutor(max_workers=max_workers) as executor:
		if iterable_kwargs is None:
			future_to_index = {
				executor.submit(func, item, *args, **kwargs): i
				for i, item in enumerate(iterable)
			}
		else:
			future_to_index = {
				executor.submit(func, item, *args, **{**kwargs, **ik}): i
				for i, (item, ik) in enumerate(zip(iterable, iterable_kwargs, strict=True))
			}
		for future in as_completed(future_to_index):
			index = future_to_index[future]
			results[index] = future.result()
	return results
