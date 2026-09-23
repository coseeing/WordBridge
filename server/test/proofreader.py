import os

import requests

base_url = "https://wordbridge.coseeing.org"
base_url = "http://localhost:8000"


def proofreader(text, token=None):
	data = {
		"request": text,
		"corrector_config_id": "default",
		"language": "zh_traditional",
		"typo_correction_mode": "standard",
		"customized_words": ["衣苑", "醫院", "視障"],
	}
	headers = {}
	if token:
		headers["Authorization"] = f"Bearer {token}"
	response = requests.post(f"{base_url}/proofreader", headers=headers, json=data)
	return response


if __name__ == "__main__":
	# Read an SSO access token from the environment -- no credentials are
	# embedded in this script. Leave SSO_ACCESS_TOKEN unset to call the
	# endpoint as a guest.
	token = os.environ.get("SSO_ACCESS_TOKEN")

	response = proofreader(
		"以經通過策驗，拿到考式吉格正書",
		token=token,
	)
	if response.status_code == 200:
		print(response.json())
	else:
		print(f"Error: {response.status_code} - {response.text}")
