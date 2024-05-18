chinese_with_phone_templates = [
	{"role": "system", "content": "輸入為文字與其正確拼音，請修正錯字並輸出正確文字:\n(文字&拼音) => 文字"},
	{"role": "user", "content": "(今天天器真好&jin1 tian1 tian1 qi4 zhen1 hao3) => "},
	{"role": "assistant", "content": "今天天氣真好"},
	{"role": "user", "content": "({{text_input}}&{{phone_input}}) => "},
]

chinese_simple_templates = [
	{"role": "system", "content": "改錯字(避免加減字，或取代原讀音的字):"},
	{"role": "user", "content": "天器真好 => "},
	{"role": "assistant", "content": "天氣真好"},
	{"role": "user", "content": "出去玩 => "},
	{"role": "assistant", "content": "出去玩"},
	{"role": "user", "content": "{{text_input}} => "},
]

chinese_comment = "'{{response_previous}}'是錯誤答案，請修正重新輸出文字"

COMMENT_DICT = {
	"ChineseTypoCorrectorSimple": chinese_comment,
	"ChineseTypoCorrector": chinese_comment,
}

TEMPLATE_DICT = {
	"ChineseTypoCorrectorSimple": chinese_simple_templates,
	"ChineseTypoCorrector": chinese_with_phone_templates,
}
