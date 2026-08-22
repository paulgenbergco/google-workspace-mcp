from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gapi import RETRIES

_PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations,addresses,biographies,photos,birthdays,urls,nicknames,memberships,userDefined"


class PeopleService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("people", "v1", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ read

    def list_contacts(
        self, max_results: int = 50, page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List the user's contacts."""
        result = self.service.people().connections().list(
            resourceName="people/me",
            pageSize=min(max_results, 100),
            pageToken=page_token,
            personFields=_PERSON_FIELDS,
            sortOrder="LAST_MODIFIED_DESCENDING",
        ).execute(num_retries=RETRIES)

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
        ).execute(num_retries=RETRIES)

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
        ).execute(num_retries=RETRIES)
        return self._parse_person(person)

    # ------------------------------------------------------------------ write

    def create_contact(
        self,
        given_name: str,
        family_name: str = "",
        middle_name: str = "",
        emails: Optional[List[str]] = None,
        phones: Optional[List[str]] = None,
        organization: str = "",
        title: str = "",
        notes: str = "",
        birthday: Optional[str] = None,
        urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new contact."""
        body: Dict[str, Any] = {
            "names": [{
                "givenName": given_name,
                "familyName": family_name,
                "middleName": middle_name,
            }],
        }
        if emails:
            body["emailAddresses"] = [{"value": e} for e in emails]
        if phones:
            body["phoneNumbers"] = [{"value": p} for p in phones]
        if organization or title:
            body["organizations"] = [{"name": organization, "title": title}]
        if notes:
            body["biographies"] = [{"value": notes}]
        if birthday:
            body["birthdays"] = [{"date": self._parse_birthday(birthday)}]
        if urls:
            body["urls"] = [{"value": u} for u in urls]

        person = self.service.people().createContact(body=body).execute(num_retries=RETRIES)
        return self._parse_person(person)

    def update_contact(
        self,
        resource_name: str,
        given_name: Optional[str] = None,
        family_name: Optional[str] = None,
        middle_name: Optional[str] = None,
        emails: Optional[List[str]] = None,
        phones: Optional[List[str]] = None,
        organization: Optional[str] = None,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        birthday: Optional[str] = None,
        urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update an existing contact."""
        # Fetch current to get etag and merge
        existing = self.service.people().get(
            resourceName=resource_name,
            personFields=_PERSON_FIELDS,
        ).execute(num_retries=RETRIES)

        update_fields = []

        if given_name is not None or family_name is not None or middle_name is not None:
            names = existing.get("names", [{}])
            name = names[0] if names else {}
            if given_name is not None:
                name["givenName"] = given_name
            if family_name is not None:
                name["familyName"] = family_name
            if middle_name is not None:
                name["middleName"] = middle_name
            existing["names"] = [name]
            update_fields.append("names")

        if emails is not None:
            existing["emailAddresses"] = [{"value": e} for e in emails]
            update_fields.append("emailAddresses")

        if phones is not None:
            existing["phoneNumbers"] = [{"value": p} for p in phones]
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

        if notes is not None:
            existing["biographies"] = [{"value": notes}]
            update_fields.append("biographies")

        if birthday is not None:
            existing["birthdays"] = [{"date": self._parse_birthday(birthday)}]
            update_fields.append("birthdays")

        if urls is not None:
            existing["urls"] = [{"value": u} for u in urls]
            update_fields.append("urls")

        person = self.service.people().updateContact(
            resourceName=resource_name,
            body=existing,
            updatePersonFields=",".join(update_fields),
        ).execute(num_retries=RETRIES)
        return self._parse_person(person)

    def delete_contact(self, resource_name: str) -> Dict[str, Any]:
        """Delete a contact."""
        self.service.people().deleteContact(resourceName=resource_name).execute(num_retries=RETRIES)
        return {"deleted": True, "resource_name": resource_name}

    # ------------------------------------------------------------------ other contacts

    def list_other_contacts(
        self, max_results: int = 50, page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List 'other contacts' (people you've interacted with but not saved)."""
        result = self.service.otherContacts().list(
            pageSize=min(max_results, 100),
            pageToken=page_token,
            readMask="names,emailAddresses,phoneNumbers",
        ).execute(num_retries=RETRIES)

        contacts = [self._parse_person(p) for p in result.get("otherContacts", [])]
        return {
            "count": len(contacts),
            "contacts": contacts,
            "nextPageToken": result.get("nextPageToken"),
        }

    # ------------------------------------------------------------------ groups

    def list_contact_groups(self, max_results: int = 50) -> Dict[str, Any]:
        """List the user's contact groups (labels)."""
        result = self.service.contactGroups().list(
            pageSize=min(max_results, 100),
        ).execute(num_retries=RETRIES)

        groups = [
            {
                "resourceName": g.get("resourceName", ""),
                "name": g.get("formattedName", g.get("name", "")),
                "memberCount": g.get("memberCount", 0),
                "groupType": g.get("groupType", ""),
            }
            for g in result.get("contactGroups", [])
        ]
        return {"count": len(groups), "groups": groups}

    def create_contact_group(self, name: str) -> Dict[str, Any]:
        """Create a new contact group (label)."""
        group = self.service.contactGroups().create(
            body={"contactGroup": {"name": name}},
        ).execute(num_retries=RETRIES)
        return {
            "resourceName": group.get("resourceName", ""),
            "name": group.get("formattedName", group.get("name", "")),
        }

    def add_to_group(
        self,
        group_resource_name: str,
        contact_resource_names: List[str],
    ) -> Dict[str, Any]:
        """Add contacts to a contact group."""
        result = self.service.contactGroups().members().modify(
            resourceName=group_resource_name,
            body={"resourceNamesToAdd": contact_resource_names},
        ).execute(num_retries=RETRIES)
        return result

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _parse_birthday(birthday: str) -> Dict[str, int]:
        """Parse a 'YYYY-MM-DD' or 'MM-DD' string into a date dict (year optional)."""
        parts = birthday.split("-")
        if len(parts) == 3:
            year, month, day = parts
            return {"year": int(year), "month": int(month), "day": int(day)}
        month, day = parts[-2], parts[-1]
        return {"month": int(month), "day": int(day)}

    @staticmethod
    def _format_birthday(date: Dict[str, Any]) -> str:
        """Format a People API date dict as 'YYYY-MM-DD' or 'MM-DD' (year optional)."""
        month = date.get("month", 0)
        day = date.get("day", 0)
        year = date.get("year")
        if year:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        return f"{int(month):02d}-{int(day):02d}"

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

        birthdays = person.get("birthdays", [])
        birthday = ""
        if birthdays:
            date = birthdays[0].get("date")
            if date:
                birthday = self._format_birthday(date)

        contact_urls = [u.get("value", "") for u in person.get("urls", [])]

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
            "birthday": birthday,
            "urls": contact_urls,
        }
