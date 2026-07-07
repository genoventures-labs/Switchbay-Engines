import json
from typing import Any, Dict, Iterable, List, Optional

import requests

from engines.Python.Facebook.fb_api import FacebookAPI, FacebookAPIError

__all__ = ["FacebookGraphQLAPI", "extract_page_insights"]


class FacebookGraphQLAPI(FacebookAPI):
    """A minimal GraphQL wrapper around the Facebook Graph API client."""

    def graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/graphql"
        params = {"access_token": self.access_token}
        payload = {"query": query}

        if variables is not None:
            payload["variables"] = variables

        response = requests.post(url, params=params, json=payload)

        try:
            result = response.json()
        except ValueError:
            raise FacebookAPIError("Invalid JSON response from Facebook GraphQL API.")

        if response.status_code != 200 or "errors" in result:
            error_payload = result.get("errors", result)
            raise FacebookAPIError(f"Facebook GraphQL error ({response.status_code}): {error_payload}")

        return result.get("data", {})

    def get_page_insights(
        self,
        page_id: str,
        metrics: Optional[Iterable[str]] = None,
        period: Optional[str] = "day",
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> Dict[str, Any]:
        if metrics is None:
            metrics = ["page_impressions", "page_engaged_users"]

        metric_list = ", ".join(f'"{metric}"' for metric in metrics)
        args = [f"metric: [{metric_list}]"]

        if period:
            args.append(f'period: "{period}"')
        if since is not None:
            args.append(f"since: {since}")
        if until is not None:
            args.append(f"until: {until}")

        args_string = ", ".join(args)
        query = f"""
        {{
          page(id: "{page_id}") {{
            name
            insights({args_string}) {{
              data {{
                name
                period
                values {{
                  value
                  end_time
                }}
              }}
            }}
          }}
        }}
        """

        return self.graphql(query)


def extract_page_insights(
    access_token: str,
    page_id: str,
    metrics: Optional[List[str]] = None,
    period: Optional[str] = "day",
    since: Optional[int] = None,
    until: Optional[int] = None,
    api_version: str = "v18.0",
) -> Dict[str, Any]:
    api = FacebookGraphQLAPI(access_token=access_token, api_version=api_version)
    return api.get_page_insights(page_id, metrics=metrics, period=period, since=since, until=until)

def create_client(access_token: str, api_version: str = "v18.0") -> FacebookGraphQLAPI:
    """Create a FacebookGraphQLAPI client instance."""
    return FacebookGraphQLAPI(access_token=access_token, api_version=api_version)
