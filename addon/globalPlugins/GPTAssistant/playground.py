from lib.proofreader import Proofreader
from lib.typo_corrector import TypoCorrector


"""
This is a quick example program that demonstrates how to use the Proofreader and TypoCorrector classes to
1. Correct typos in a sample text string
2. Analyze the differences between original and corrected texts
"""
if __name__ == "__main__":
	# Initialize the typo corrector object with the OpenAI API key and the GPT model
	corrector = TypoCorrector(model="text-davinci-003", api_key="OPENAI_API_KEY")

	# Initialize the proofreader object using the typo corrector
	proofreader = Proofreader(corrector)

	text = "天器真好，想出去完"
	text_corrected, diff = proofreader.typo_analyzer(text)
	print(f"text = {text}, text_corrected = {text_corrected}, diff = {diff}")

"""
Output:
text = 天器真好，想出去完,
text_corrected = 天氣真好，想出去玩,
diff = [
	{
		'operation': 'equal',
		'before_text': '天',
		'after_text': '天',
		'index_start_before': 0,
		'index_end_before': 1,
		'index_start_after': 0,
		'index_end_after': 1,
		'before_descs': '',
		'after_descs': '',
		'tags': None
	},
	{
		'operation': 'replace',
		'before_text': '器',
		'after_text': '氣',
		'index_start_before': 1,
		'index_end_before': 2,
		'index_start_after': 1,
		'index_end_after': 2,
		'before_descs': '',
		'after_descs': '',
		'tags': ['Share the same pronunciation']
	},
	{
		'operation': 'equal',
		'before_text': '真好，想出去',
		'after_text': '真好 ，想出去',
		'index_start_before': 2,
		'index_end_before': 8,
		'index_start_after': 2,
		'index_end_after': 8,
		'before_descs': '',
		'after_descs': '',
		'tags': None
	},
	{
		'operation': 'replace',
		'before_text': '完',
		'after_text': '玩',
		'index_start_before': 8,
		'index_end_before': 9,
		'index_start_after': 8,
		'index_end_after': 9,
		'before_descs': '',
		'after_descs': '',
		'tags': ['Share the same pronunciation']
	}
]
"""
