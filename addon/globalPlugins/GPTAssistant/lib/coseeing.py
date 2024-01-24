import requests


OPENAIRELAY_URL = "http://openairelay.coseeing.org"

def obtain_openai_key(coseeing_username, coseeing_password):
	auth_data = {
		"username": coseeing_username,
		"password": coseeing_password,
	}

	# Send POST request to /login endpoint to obtain key token
	response = requests.post(f"{OPENAIRELAY_URL}/login", data=auth_data)

	# Check if response is successful
	if response.status_code == 200:
		try:
			# Get token from response
			token = response.json()["access_token"]
		except:
			token = None
	else:
		token = None

	return token
