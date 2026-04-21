from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations,addresses,biographies,photos"


class PeopleService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("people", "v1", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ read

    def list_contacts(self, max_results: int = 50) -> Dict[str, Any]:
        """List the user's contacts."""
        result = self.service.people().connections().list(
            resourceName="people/me",
            pageSize=min(max_results, 100),
            personFields=_PERSON_FIELDS,
            sortOrder="LAST_MODIFIED_DESCENDING",
        ).execute()

        contacts = [self._parse_person(p) for p in result.get("connections", [])]
        return {
            "count": len(contacts),
            "contacts": contacts,
            "nextPageToken": result.get("nextPageToken"),
        }

    def search_contacts(self, query: str, max_results: int = 20) -> Dict[str, Any]:
        """Search contacts by name, email, phone, etc."""
        result = self.service.people().searchContacts(
            query=query,
            pageSize=min(max_results, 30),
            readMask=_PERSON_FIELDS,
        ).execute()

        contacts = [
            self._parse_person(r.get("person", {}))
            for r in result.get("results", [])
        ]
        return {"query": query, "count": len(contacts), "contacts": contacts}

    def get_contact(self, resource_name: str) -> Dict[str, Any]:
        """Get a single contact by resource name (e.g. 'people/c1234')."""
        person = self.service.people().get(
            resourceName=resource_name,
            personFields=_PERSON_FIELDS,
        ).execute()
        return self._parse_person(person)

    # ------------------------------------------------------------------ write

    def create_contact(
        self,
        given_name: str,
        family_name: str = "",
        email: str = "",
        phone: str = "",
        organization: str = "",
        title: str = "",
    ) -> Dict[str, Any]:
        """Create a new contact."""
        body: Dict[str, Any] = {
            "names": [{"givenName": given_name, "familyName": family_name}],
        }
        if email:
            body["emailAddresses"] = [{"value": email}]
        if phone:
            body["phoneNumbers"] = [{"value": phone}]
        if organization or title:
            body["organizations"] = [{"name": organization, "title": title}]

        person = self.service.people().createContact(body=body).execute()
        return self._parse_person(person)

    def update_contact(
        self,
        resource_name: str,
        given_name: Optional[str] = None,
        family_name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        organization: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing contact."""
        # Fetch current to get etag and merge
        existing = self.service.people().get(
            resourceName=resource_name,
            personFields=_PERSON_FIELDS,
        ).execute()

        update_fields = []

        if given_name is not None or family_name is not None:
            names = existing.get("names", [{}])
            name = names[0] if names else {}
            if given_name is not None:
                name["givenName"] = given_name
            if family_name is not None:
                name["familyName"] = family_name
            existing["names"] = [name]
            update_fields.append("names")

        if email is not None:
            existing["emailAddresses"] = [{"value": email}]
            update_fields.append("emailAddresses")

        if phone is not None:
            existing["phoneNumbers"] = [{"value": phone}]
            update_fields.append("phoneNumbers")

        if organization is not None or title is not None:
            orgs = existing.get("organizations", [{}])
            org = orgs[0] if orgs else {}
            if organization is not None:
                org["name"] = organization
            if title is not None:
                org["title"] = title
            existing["organizations"] = [org]
            update_fields.append("organizations")

        person = self.service.people().updateContact(
            resourceName=resource_name,
            body=existing,
            updatePersonFields=",".join(update_fields),
        ).execute()
        return self._parse_person(person)

    def delete_contact(self, resource_name: str) -> Dict[str, Any]:
        """Delete a contact."""
        self.service.people().deleteContact(resourceName=resource_name).execute()
        return {"deleted": True, "resource_name": resource_name}

    # ------------------------------------------------------------------ internals

    def _parse_person(self, person: Dict[str, Any]) -> Dict[str, Any]:
        names = person.get("names", [])
        name = names[0] if names else {}

        emails = [
            {"value": e.get("value", ""), "type": e.get("type", "")}
            for e in person.get("emailAddresses", [])
        ]

        phones = [
            {"value": p.get("value", ""), "type": p.get("type", "")}
            for p in person.get("phoneNumbers", [])
        ]

        orgs = [
            {"name": o.get("name", ""), "title": o.get("title", "")}
            for o in person.get("organizations", [])
        ]

        photos = [p.get("url", "") for p in person.get("photos", [])]

        return {
            "resourceName": person.get("resourceName", ""),
            "name": name.get("displayName", ""),
            "givenName": name.get("givenName", ""),
            "familyName": name.get("familyName", ""),
            "emails": emails,
            "phones": phones,
            "organizations": orgs,
            "addresses": [
                a.get("formattedValue", "") for a in person.get("addresses", [])
            ],
            "bio": (person.get("biographies", [{}])[0].get("value", "")
                    if person.get("biographies") else ""),
            "photo": photos[0] if photos else "",
        }
