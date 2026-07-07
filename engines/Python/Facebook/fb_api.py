import requests


class FacebookAPIError(Exception):
    """Raised when the Facebook Graph API returns an error."""


class FacebookAPI:
    """A minimal Facebook Graph API SDK wrapper.

    Example:
        fb = FacebookAPI(access_token="YOUR_TOKEN")
        profile = fb.get("me", fields="id,name")
    """

    def __init__(self, access_token: str, api_version: str = "v18.0"):
        if not access_token:
            raise ValueError("access_token is required")
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    def _request(self, method: str, path: str, params=None, data=None):
        if params is None:
            params = {}
        params["access_token"] = self.access_token

        url = f"{self.base_url}/{path.lstrip('/')}"

        response = requests.request(method, url, params=params, data=data)
        content_type = response.headers.get("Content-Type", "")

        if response.status_code != 200:
            try:
                error = response.json().get("error", response.text)
            except ValueError:
                error = response.text
            raise FacebookAPIError(f"Facebook API error ({response.status_code}): {error}")

        if "application/json" in content_type:
            return response.json()

        return response.text

    def get(self, path: str, **params):
        """Perform a GET request to the Graph API.

        Args:
            path: The Graph API endpoint path (for example, "me" or "12345/feed").
            **params: Query parameters for the request.

        Returns:
            Parsed JSON response or raw text if non-JSON.
        """
        return self._request("GET", path, params=params)

    def post(self, path: str, **data):
        """Perform a POST request to the Graph API.

        Args:
            path: The Graph API endpoint path.
            **data: Body parameters for the request.

        Returns:
            Parsed JSON response or raw text if non-JSON.
        """
        return self._request("POST", path, data=data)

    def delete(self, path: str, **params):
        """Perform a DELETE request to the Graph API."""
        return self._request("DELETE", path, params=params)

    def get_fields(self, path: str, fields, **params):
        """Perform a GET request and request specific fields."""
        if isinstance(fields, (list, tuple)):
            fields = ",".join(fields)
        params["fields"] = fields
        return self.get(path, **params)

    def get_edge(self, node_id: str, edge: str, **params):
        """Get an edge for a given node, like posts or photos."""
        return self.get(f"{node_id}/{edge}", **params)

    def post_edge(self, node_id: str, edge: str, **data):
        """Post to an edge for a given node."""
        return self.post(f"{node_id}/{edge}", **data)

    def delete_edge(self, node_id: str, edge: str, **params):
        """Delete an edge for a given node."""
        return self.delete(f"{node_id}/{edge}", **params)

    def get_object(self, object_id: str, **params):
        """Get an object by its ID."""
        return self.get(object_id, **params)

def create_client(access_token: str, api_version: str = "v18.0") -> FacebookAPI:
    """Factory helper to create a FacebookAPI client."""
    return FacebookAPI(access_token, api_version)
