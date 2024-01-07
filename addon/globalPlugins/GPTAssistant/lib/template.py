typo_corrector_templates = \
"""改錯字(避免加字或減字，或取代原讀音的字):
Q:天器 A:天氣
Q:{{text_input}} A:"""

typo_corrector_by_phone_templates = \
"""拼音轉{{text_type}}
Q:{{pinyin_input}} A:"""

typo_corrector_with_phone_templates = \
"""輸入為文字與其正確拼音，請修正錯字並輸出正確文字:
(文字&拼音) => 文字
(今天天器真好&jin1 tian1 tian1 qi4 zhen1 hao3) => 今天天氣真好
({{text_input}}&{{phone_input}}) => """

typo_corrector_with_phone_chat_templates = [
	{"role": "system", "content": "輸入為文字與其正確拼音，請修正錯字並輸出正確文字:\n(文字&拼音) => 文字"},
	{"role": "user", "content": "(今天天器真好&jin1 tian1 tian1 qi4 zhen1 hao3) => "},
	{"role": "assistant", "content": "今天天氣真好"},
	{"role": "user", "content": "({{text_input}}&{{phone_input}}) => "},
]

typo_identifier_templates = \
"""輸出句子中帶有錯字的詞彙並修正 (誤重新輸出題目，全對請輸出None)
example:
今天早點修息吧!明天還要早豈呢 => (修習,休息)(早豈,早起)
今天玩得很開心，希望下次還能一起出去玩 => None
好累喔!想早點休習 => """

TEMPLATE_DICT = {
	"TypoCorrector": typo_corrector_templates,
	"TypoCorrectorWithPhone": typo_corrector_with_phone_templates,
	"TypoCorrectorWithPhoneChat": typo_corrector_with_phone_chat_templates,
	"TypoCorrectorByPhone": typo_corrector_by_phone_templates,
	"TypoIdentifier": typo_identifier_templates,
}
