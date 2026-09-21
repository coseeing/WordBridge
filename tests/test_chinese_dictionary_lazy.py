import subprocess
import sys
import textwrap
import threading
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"

BOOTSTRAP = textwrap.dedent(
	f"""
	import sys
	import types
	from pathlib import Path

	ADDON = Path({str(ADDON_PATH)!r})
	sys.path.insert(0, str(ADDON))

	addon_handler = types.ModuleType("addonHandler")
	addon_handler.initTranslation = lambda: None
	sys.modules["addonHandler"] = addon_handler

	from lib import vendor

	vendor.install(vendor.default_roots(str(ADDON / "package")))
	"""
)


def _run(code: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		[sys.executable, "-c", BOOTSTRAP + textwrap.dedent(code)],
		capture_output=True,
		text=True,
	)


def test_importing_the_diff_utilities_does_not_read_the_dictionary():
	# A subprocess, because another test module may already have warmed the
	# cache in this process.
	result = _run(
		"""
		import lib.tasks.typo.utils  # noqa: F401
		from lib.tasks.typo import chinese_dictionary

		assert chinese_dictionary._MAPPINGS is None, "the dictionary was parsed at import time"
		"""
	)
	assert result.returncode == 0, result.stderr


def test_the_dictionary_loads_on_first_use_and_is_reused():
	result = _run(
		"""
		from lib.tasks.typo import chinese_dictionary

		calls = []
		original = chinese_dictionary.load_pinyin_mapping

		def counting():
			calls.append(1)
			return original()

		chinese_dictionary.load_pinyin_mapping = counting

		first = chinese_dictionary.get_string_to_pinyin()
		second = chinese_dictionary.get_pinyin_to_string()
		third = chinese_dictionary.get_string_to_pinyin()

		assert len(calls) == 1, calls
		assert first is third
		assert len(first) > 1000, len(first)
		assert len(second) > 100, len(second)
		"""
	)
	assert result.returncode == 0, result.stderr


def test_concurrent_first_access_loads_exactly_once():
	result = _run(
		"""
		import threading
		from lib.tasks.typo import chinese_dictionary

		calls = []
		original = chinese_dictionary.load_pinyin_mapping
		start = threading.Barrier(8)

		def slow():
			calls.append(1)
			return original()

		chinese_dictionary.load_pinyin_mapping = slow

		seen = []

		def worker():
			start.wait()
			seen.append(chinese_dictionary.get_string_to_pinyin())

		threads = [threading.Thread(target=worker) for _ in range(8)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()

		assert len(calls) == 1, calls
		assert all(mapping is seen[0] for mapping in seen)
		"""
	)
	assert result.returncode == 0, result.stderr


def test_a_missing_dictionary_file_raises():
	result = _run(
		"""
		from pathlib import Path

		from lib.tasks.typo import chinese_dictionary

		chinese_dictionary.DICTIONARY_PATH = Path("/nonexistent/wordbridge.csv")
		chinese_dictionary._MAPPINGS = None

		try:
			chinese_dictionary.get_string_to_pinyin()
		except OSError:
			pass
		else:
			raise AssertionError("a missing dictionary must raise, not degrade to an empty mapping")
		"""
	)
	assert result.returncode == 0, result.stderr


def test_repeated_misses_do_not_grow_the_process_lifetime_mapping():
	# get_string_to_pinyin()/get_pinyin_to_string() return the same defaultdict
	# for the whole process. .get(char, []) (rather than the defaultdict's []
	# subscript) is load-bearing: [] would insert a new empty entry for every
	# distinct character that misses, an unbounded process-lifetime leak for
	# any caller fed arbitrary text (lookup_char_pinyin has none of the
	# validation get_char_pinyin does). A subprocess, because another test
	# module may already have warmed the cache in this process.
	result = _run(
		"""
		from lib.tasks.typo import chinese_dictionary
		from lib.tasks.typo.utils import analyze_diff, lookup_char_pinyin

		before = len(chinese_dictionary.get_string_to_pinyin())

		# A stream of distinct characters from outside the CJK block the
		# dictionary is drawn from, guaranteed to miss on every lookup.
		misses = [chr(0x1F300 + offset) for offset in range(500)]
		for char in misses:
			lookup_char_pinyin(char)
		for char_original, char_corrected in zip(misses, misses[1:]):
			analyze_diff(char_original, char_corrected)

		after = len(chinese_dictionary.get_string_to_pinyin())
		assert after == before, (before, after)
		"""
	)
	assert result.returncode == 0, result.stderr
