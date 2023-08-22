typo_corrector_templates = [
"""改錯字(避免加字或減字，或取代原讀音的字):
Q:天器 A:天氣
Q:{{text_input}} A:
""",
"""
改錯字，修正箭頭左側的錯字修正後輸出:
天器 => 天氣
{{text_input}} => """,
]

typo_corrector_by_phone_templates = [
"""拼音轉{{text_type}}
Q:{{pinyin_input}} A:""",
]

typo_corrector_with_phone_templates = [
"""請先按照原句子的語意輸出句子的拼音，再將拼音轉回文字並修正錯字並在結尾加上#(最終句子的拼音、字數需與原句相同，避免加字或減字且語意要合理):
文字 => 拼音 => 文字#
今天天器真好 => jīn tiān tiān qì zhēn hǎo => 今天天氣真好#
{{text_input}} => {{phone_input}} => """,
]

typo_identifier_templates = [
"""輸出句子中帶有錯字的詞彙並修正 (誤重新輸出題目，全對請輸出None)
example:
今天早點修息吧!明天還要早豈呢 => (修習,休息)(早豈,早起)
今天玩得很開心，希望下次還能一起出去玩 => None
好累喔!想早點休習 => """,
]

TEMPLATE_DICT = {
	"TypoCorrector": typo_corrector_templates,
	"TypoCorrectorWithPhone": typo_corrector_with_phone_templates,
	"TypoCorrectorByPhone": typo_corrector_by_phone_templates,
	"TypoIdentifier": typo_identifier_templates,
}
