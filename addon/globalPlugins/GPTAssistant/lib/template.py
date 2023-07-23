typo_corrector_templates = [
"""改錯字:
天器 => 天氣
{{text_input}} => 
""",
"""
改錯字，修正箭頭左側的錯字修正後輸出:
天器 => 天氣
{{text_input}} => """,
]

typo_identifier_templates = [
"""輸出句子中帶有錯字的詞彙並修正 (誤重新輸出題目，全對請輸出None)
example:
今天早點修息吧!明天還要早豈呢 => (修習,休息)(早豈,早起)
今天玩得很開心，希望下次還能一起出去玩 => None
好累喔!想早點休習 => """,
]

TEMPLATE_DICT = {"TypoCorrector": typo_corrector_templates, "TypoIdentifier": typo_identifier_templates, }
