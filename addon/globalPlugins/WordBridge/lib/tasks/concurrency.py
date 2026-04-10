from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed


def parallel_map(
	func: Callable,
	iterable: Iterable,
	max_workers: int = 20,
	iterable_kwargs: Iterable[dict] = None,
	*args,
	**kwargs
) -> list:
	"""
	Execute a function over an iterable in parallel using a thread pool.
	Returns results in the same order as the input iterable.
	"""
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
				for i, (item, ik) in enumerate(zip(iterable, iterable_kwargs))
			}
		for future in as_completed(future_to_index):
			index = future_to_index[future]
			results[index] = future.result()
	return results
