import logging
import random
import requests
import time


OPENAIRELAY_URL = "http://openairelay.coseeing.org"
log = logging.getLogger(__name__)


def obtain_openai_key(coseeing_username, coseeing_password):
	auth_data = {
		"username": coseeing_username,
		"password": coseeing_password,
	}
	httppost_retries = 2
	backoff = 1

	# Send POST request to /login endpoint to obtain key token
	response = None
	request_error = None
	for r in range(httppost_retries):
		try:
			response = requests.post(
				f"{OPENAIRELAY_URL}/login",
				data=auth_data,
				timeout=3,
			)
			break
		except Exception as e:
			request_error = type(e).__name__
			log.error(
				f"Try = {r + 1}, {request_error}, an error occurred when sending request to Coseeing: {e}"
			)
			backoff = min(backoff * (1 + random.random()), 3)
			time.sleep(backoff)

	if response is None:
		raise Exception(f"HTTP請求錯誤({request_error})，請檢查網路設定")

	# Check if response is successful
	if response.status_code == 200:
		# Get token from response
		token = response.json()["access_token"]
	elif response.status_code == 400:
		raise Exception("帳號的使用者名稱或密碼有誤，請檢察Coseeing帳號的使用者名稱或密碼是否正確")
	else:
		raise Exception(f"HTTP錯誤，代碼={response.status_code}")

	return token
