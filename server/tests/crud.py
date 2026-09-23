import os

import requests

base_url = "http://localhost:8000"


def _headers(token):
	return {"Authorization": f"Bearer {token}"}


def list_interactions(token):
	response = requests.get(f"{base_url}/interactions", headers=_headers(token))
	return response


def read_user(pk, token):
	response = requests.get(f"{base_url}/users/{pk}", headers=_headers(token))
	return response


if __name__ == "__main__":
	# Admin CRUD requires a superuser SSO access token, read from the
	# environment -- no credentials or tokens are embedded in this script.
	token = os.environ.get("SSO_ACCESS_TOKEN")
	if not token:
		print("set SSO_ACCESS_TOKEN to a superuser access token to run this script")
	else:
		response = list_interactions(token)
		if response.status_code == 200:
			print(len(response.json()["data"]))
		else:
			print(f"Error: {response.status_code} - {response.text}")
