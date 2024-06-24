message_zh_traditional_tw = [
	{"role": "user", "content": "{{QUESTION}}今天天器真好&jin1 tian1 tian1 qi4 zhen1 hao3 => "},
	{"role": "assistant", "content": "{{ANSWER}}今天天氣真好"},
	{"role": "user", "content": "{{QUESTION}}{{text_input}}&{{phone_input}} => "},
]

message_lite_zh_traditional_tw = [
	{"role": "user", "content": "天器真好 => "},
	{"role": "assistant", "content": "天氣真好"},
	{"role": "user", "content": "出去玩 => "},
	{"role": "assistant", "content": "出去玩"},
	{"role": "user", "content": "{{text_input}} => "},
]

message_zh_simplified = [
	{"role": "user", "content": "{{QUESTION}}今天天器真好&jin1 tian1 tian1 qi4 zhen1 hao3 => "},
	{"role": "assistant", "content": "{{ANSWER}}今天天气真好"},
	{"role": "user", "content": "{{QUESTION}}{{text_input}}&{{phone_input}} => "},
]

message_lite_zh_simplified = [
	{"role": "user", "content": "天器真好 => "},
	{"role": "assistant", "content": "天气真好"},
	{"role": "user", "content": "出去玩 => "},
	{"role": "assistant", "content": "出去玩"},
	{"role": "user", "content": "{{text_input}} => "},
]

comment_zh_traditional_tw = "'{{response_previous}}'是錯誤答案，請修正重新輸出文字"
comment_zh_simplified = "'{{response_previous}}'是错误答案，请修正重新输出文字"

system_zh_traditional_tw = "輸入為文字與其正確拼音，請修正錯字並輸出正確文字:\n(文字&拼音) => 文字"
system_lite_zh_traditional_tw = "改錯字(避免加減字，或取代原讀音的字):"
system_zh_simplified = "输入为文字与其正确拼音，请修正错字并输出正确文字:\n(文字&拼音) => 文字"
system_lite_zh_simplified = "改错字(避免加减字，或取代原读音的字):"

COMMENT_TEMPLATE_DICT = {
	"ChineseTypoCorrectorLite": {
		"zh_traditional_tw": comment_zh_traditional_tw,
		"zh_simplified": comment_zh_simplified,
	},
	"ChineseTypoCorrector": {
		"zh_traditional_tw": comment_zh_traditional_tw,
		"zh_simplified": comment_zh_simplified,
	}
}

MESSAGE_TEMPLATE_DICT = {
	"ChineseTypoCorrectorLite": {
		"zh_traditional_tw": message_lite_zh_traditional_tw,
		"zh_simplified": message_lite_zh_simplified,
	},
	"ChineseTypoCorrector": {
		"zh_traditional_tw": message_zh_traditional_tw,
		"zh_simplified": message_zh_simplified,
	}
}

SYSTEM_TEMPLATE_DICT = {
	"ChineseTypoCorrectorLite": {
		"zh_traditional_tw": system_lite_zh_traditional_tw,
		"zh_simplified": system_lite_zh_simplified,
	},
	"ChineseTypoCorrector": {
		"zh_traditional_tw": system_zh_traditional_tw,
		"zh_simplified": system_zh_simplified,
	}
}
