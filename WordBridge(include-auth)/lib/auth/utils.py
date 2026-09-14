from concurrent.futures import Future
import threading

def run_in_thread(func, *args, **kwargs) -> Future:
	fut = Future()

	def _target():
		try:
			res = func(*args, **kwargs)
		except Exception as e:
			try:
				fut.set_exception(e)
			except Exception:
				pass
		else:
			try:
				fut.set_result(res)
			except Exception:
				pass

	threading.Thread(target=_target, daemon=True).start()
	return fut


def then(fut: Future, fn, executor=None) -> Future:
	"""當 fut 成功 -> out.set_result(fn(result));
	   fut 失敗 -> out.set_exception(...)
	   fut 取消 -> out.cancel()
	   若提供 executor，fn 會丟到 executor 跑（避免卡住完成該 future 的執行緒）。
	"""
	out = Future()

	def _finish_with_exception(exc):
		if not out.done():
			out.set_exception(exc)

	def _cb(f: Future):
		if f.cancelled():
			out.cancel(); return
		try:
			value = f.result()  # 這裡會把原本的例外拋出
			if executor:
				def _run():
					try:
						out.set_result(fn(value))
					except Exception as e:
						_finish_with_exception(e)
				executor.submit(_run)
			else:
				out.set_result(fn(value))
		except Exception as e:
			_finish_with_exception(e)

	fut.add_done_callback(_cb)
	return out


def then_future(fut: Future, fn) -> Future:
	"""fn(result) 必須回傳一個 Future；此函式把它『扁平化』成單一 Future。"""
	out = Future()

	def _pipe(src: Future, dst: Future):
		if src.cancelled():
			dst.cancel()
		else:
			exc = src.exception()
			if exc:
				if not dst.done():
					dst.set_exception(exc)
			else:
				if not dst.done():
					dst.set_result(src.result())

	def _cb(f: Future):
		if f.cancelled():
			out.cancel(); return
		try:
			value = f.result()
			next_f = fn(value)  # -> Future
			next_f.add_done_callback(lambda nf: _pipe(nf, out))
		except Exception as e:
			if not out.done():
				out.set_exception(e)

	fut.add_done_callback(_cb)
	return out


def tap(fut: Future, fn) -> Future:
	"""完成時先執行副作用 fn(fut)，再把原結果傳遞給新的 Future。"""
	out = Future()
	def _cb(f: Future):
		try:
			fn(f)  # 副作用（可用 wx.CallAfter 切回 UI）
		finally:
			if f.cancelled():
				out.cancel()
			else:
				exc = f.exception()
				if exc:
					out.set_exception(exc)
				else:
					out.set_result(f.result())
	fut.add_done_callback(_cb)
	return out


def observe(fut: Future, fn) -> Future:
	def _cb(f: Future):
		try:
			fn(f)
		except Exception as e:
			pass
	fut.add_done_callback(_cb)
	return fut
