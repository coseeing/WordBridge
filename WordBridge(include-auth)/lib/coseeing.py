import logging
import random
import requests
import time

log = logging.getLogger(__name__)


def obtain_openai_key(coseeing_url, coseeing_username, coseeing_password):
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
				f"{coseeing_url}/login",
				data=auth_data,
				timeout=3,
			)
			break
		except Exception as e:
			request_error = type(e).__name__
			log.error(
				_("Try = {try_index}, {request_error}, an error occurred when sending request to Coseeing: {e}".format(
					try_index=(r + 1),
					request_error=request_error, e=e)
				)
			)
			backoff = min(backoff * (1 + random.random()), 3)
			time.sleep(backoff)

	if response is None:
		raise Exception(
			_("HTTP request error ({request_error}). Please check the network setting.").format(
				request_error=request_error
			)
		)

	# Check if response is successful
	if response.status_code == 400:
		raise Exception(_("The username or password for the Coseeing account is incorrect."))
	elif response.status_code != 200:
		raise Exception(_("Unknown errors. Status code = {status_code}").format(status_code=response.status_code))

	# Get token from response
	token = response.json()["access_token"]

	return token
