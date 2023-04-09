from typing import List
from utils import strings_diff, text_segmentation
from typo_corrector import TypoCorrector


class SegmentReport():

	def __init__(self, segment_original: str, segment_corrected: str):
		self.segment_original = segment_original
		self.segment_corrected = segment_corrected
		self.diff = strings_diff(self.segment_original, self.segment_corrected)

	def __repr__(self):
		report_str = "SegmentReport<\n"
		report_str += f"	segment_original = \"{self.segment_original}\",\n"
		report_str += f"	segment_corrected = \"{self.segment_corrected}\",\n"
		report_str += f"	diff = {self.diff}\n"
		report_str += ">\n"
		return report_str

class Proofreader():

	def __init__(self, segment_corrector: TypoCorrector):
		self.segment_corrector = segment_corrector

	def typo_analyzer(self, text: str, fake_operation: bool=False) -> List[SegmentReport]:
		segment_reports = []
		for segment in text_segmentation(text):
			segment_corrected = self.segment_corrector.correct_string(segment, fake_operation)
			segment_reports.append(SegmentReport(segment, segment_corrected))
			
		return segment_reports

if __name__ == "__main__":
	corrector = TypoCorrector(model="text-davinci-003",
								api_key="OPENAI_API_KEY")

	proofreader = Proofreader(corrector)
	segment_reports = proofreader.typo_analyzer("天器真好，想出去完")
	print(segment_reports)

"""
Output:

[SegmentReport<
        segment_original = "天器真好，",
        segment_corrected = "天氣真好，",
        diff = [{'operation': 'replace', 'index_start1': 1, 'index_end1': 2, 'index_start2': 1, 'index_end2': 2}]
>
, SegmentReport<
        segment_original = "想出去完",
        segment_corrected = "想出去玩",
        diff = [{'operation': 'replace', 'index_start1': 3, 'index_end1': 4, 'index_start2': 3, 'index_end2': 4}]
>
]
"""