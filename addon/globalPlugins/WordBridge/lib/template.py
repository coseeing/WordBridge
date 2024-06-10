zh_with_phone_traditional_tw = [
	{"role": "system", "content": "輸入為文字與其正確拼音，請修正錯字並輸出正確文字:\n(文字&拼音) => 文字"},
	{"role": "user", "content": "{{QUESTION}}今天天器真好&jin1 tian1 tian1 qi4 zhen1 hao3 => "},
	{"role": "assistant", "content": "{{ANSWER}}今天天氣真好"},
	{"role": "user", "content": "{{QUESTION}}{{text_input}}&{{phone_input}} => "},
]

zh_simple_traditional_tw = [
	{"role": "system", "content": "改錯字(避免加減字，或取代原讀音的字):"},
	{"role": "user", "content": "天器真好 => "},
	{"role": "assistant", "content": "天氣真好"},
	{"role": "user", "content": "出去玩 => "},
	{"role": "assistant", "content": "出去玩"},
	{"role": "user", "content": "{{text_input}} => "},
]

zh_with_phone_simplified = [
	{"role": "system", "content": "输入为文字与其正确拼音，请修正错字并输出正确文字:\n(文字&拼音) => 文字"},
	{"role": "user", "content": "{{QUESTION}}今天天器真好&jin1 tian1 tian1 qi4 zhen1 hao3 => "},
	{"role": "assistant", "content": "{{ANSWER}}今天天气真好"},
	{"role": "user", "content": "{{QUESTION}}{{text_input}}&{{phone_input}} => "},
]

zh_simple_simplified = [
	{"role": "system", "content": "改错字(避免加减字，或取代原读音的字):"},
	{"role": "user", "content": "天器真好 => "},
	{"role": "assistant", "content": "天气真好"},
	{"role": "user", "content": "出去玩 => "},
	{"role": "assistant", "content": "出去玩"},
	{"role": "user", "content": "{{text_input}} => "},
]

zh_comment_traditional_tw = "'{{response_previous}}'是錯誤答案，請修正重新輸出文字"
zh_comment_simplified = "'{{response_previous}}'是错误答案，请修正重新输出文字"

COMMENT_DICT = {
	"ChineseTypoCorrectorSimple":{
		"zh_traditional_tw": zh_comment_traditional_tw,
		"zh_simplified": zh_comment_simplified,
	},
	"ChineseTypoCorrector":{
		"zh_traditional_tw": zh_comment_traditional_tw,
		"zh_simplified": zh_comment_simplified,
	}
}

TEMPLATE_DICT = {
	"ChineseTypoCorrectorSimple":{
		"zh_traditional_tw": zh_simple_traditional_tw,
		"zh_simplified": zh_simple_simplified,
	},
	"ChineseTypoCorrector":{
		"zh_traditional_tw": zh_with_phone_traditional_tw,
		"zh_simplified": zh_with_phone_simplified,
	}
}
