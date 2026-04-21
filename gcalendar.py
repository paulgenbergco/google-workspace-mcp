from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class CalendarService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("calendar", "v3", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ calendars

    def list_calendars(self) -> List[Dict[str, Any]]:
        result = self.service.calendarList().list().execute()
        return [
            {
                "id": cal["id"],
                "summary": cal.get("summary", ""),
                "description": cal.get("description", ""),
                "primary": cal.get("primary", False),
                "accessRole": cal.get("accessRole", ""),
                "backgroundColor": cal.get("backgroundColor", ""),
            }
            for cal in result.get("items", [])
        ]

    # ------------------------------------------------------------------ events

    def list_events(
        self,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 20,
        calendar_id: str = "primary",
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        params: Dict[str, Any] = {
            "calendarId": calendar_id,
            "maxResults": min(max_results, 50),
            "singleEvents": True,
            "orderBy": "startTime",
            "timeMin": time_min or now,
        }
        if time_max:
            params["timeMax"] = time_max

        result = self.service.events().list(**params).execute()
        events = [self._parse_event(e) for e in result.get("items", [])]
        return {
            "calendar_id": calendar_id,
            "count": len(events),
            "events": events,
            "nextPageToken": result.get("nextPageToken"),
        }

    def search_events(
        self,
        query: str,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 20,
        calendar_id: str = "primary",
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        params: Dict[str, Any] = {
            "calendarId": calendar_id,
            "q": query,
            "maxResults": min(max_results, 50),
            "singleEvents": True,
            "orderBy": "startTime",
            "timeMin": time_min or now,
        }
        if time_max:
            params["timeMax"] = time_max

        result = self.service.events().list(**params).execute()
        events = [self._parse_event(e) for e in result.get("items", [])]
        return {
            "query": query,
            "count": len(events),
            "events": events,
        }

    def get_event(self, event_id: str, calendar_id: str = "primary") -> Dict[str, Any]:
        event = self.service.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute()
        return self._parse_event(event)

    # ------------------------------------------------------------------ write

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        calendar_id: str = "primary",
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        all_day: bool = False,
        add_meet: bool = False,
    ) -> Dict[str, Any]:
        """Create a calendar event."""
        if all_day:
            event_body: Dict[str, Any] = {
                "summary": summary,
                "start": {"date": start},
                "end": {"date": end},
            }
        else:
            event_body = {
                "summary": summary,
                "start": {"dateTime": start},
                "end": {"dateTime": end},
            }

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]
        if add_meet:
            event_body["conferenceData"] = {
                "createRequest": {"requestId": f"mcp-{summary[:20]}"}
            }

        params: Dict[str, Any] = {
            "calendarId": calendar_id,
            "body": event_body,
            "sendUpdates": "all",
        }
        if add_meet:
            params["conferenceDataVersion"] = 1

        result = self.service.events().insert(**params).execute()
        return self._parse_event(result)

    def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        summary: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update fields on an existing event."""
        existing = self.service.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute()

        if summary is not None:
            existing["summary"] = summary
        if description is not None:
            existing["description"] = description
        if location is not None:
            existing["location"] = location
        if start is not None:
            if "date" in existing.get("start", {}):
                existing["start"] = {"date": start}
            else:
                existing["start"] = {"dateTime": start}
        if end is not None:
            if "date" in existing.get("end", {}):
                existing["end"] = {"date": end}
            else:
                existing["end"] = {"dateTime": end}
        if attendees is not None:
            existing["attendees"] = [{"email": e} for e in attendees]

        result = self.service.events().update(
            calendarId=calendar_id, eventId=event_id, body=existing, sendUpdates="all"
        ).execute()
        return self._parse_event(result)

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> Dict[str, Any]:
        """Delete a calendar event."""
        self.service.events().delete(
            calendarId=calendar_id, eventId=event_id, sendUpdates="all"
        ).execute()
        return {"deleted": True, "event_id": event_id}

    def respond_to_event(
        self,
        event_id: str,
        response: str,
        calendar_id: str = "primary",
    ) -> Dict[str, Any]:
        """Respond to an event invitation (accepted, declined, tentative)."""
        event = self.service.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute()

        for attendee in event.get("attendees", []):
            if attendee.get("self"):
                attendee["responseStatus"] = response
                break

        result = self.service.events().update(
            calendarId=calendar_id, eventId=event_id, body=event, sendUpdates="all"
        ).execute()
        return self._parse_event(result)

    def find_free_time(
        self,
        emails: List[str],
        time_min: str,
        time_max: str,
    ) -> Dict[str, Any]:
        """Query free/busy information for a list of people."""
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": e} for e in emails],
        }
        result = self.service.freebusy().query(body=body).execute()

        calendars = {}
        for email, info in result.get("calendars", {}).items():
            calendars[email] = {
                "busy": [
                    {"start": b["start"], "end": b["end"]}
                    for b in info.get("busy", [])
                ],
                "errors": info.get("errors", []),
            }

        return {
            "timeMin": result.get("timeMin", time_min),
            "timeMax": result.get("timeMax", time_max),
            "calendars": calendars,
        }

    # ------------------------------------------------------------------ internals

    def _parse_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        start = event.get("start", {})
        end = event.get("end", {})

        attendees = [
            {
                "email": a.get("email", ""),
                "name": a.get("displayName", ""),
                "response": a.get("responseStatus", ""),
                "self": a.get("self", False),
            }
            for a in event.get("attendees", [])
        ]

        return {
            "id": event.get("id", ""),
            "summary": event.get("summary", "(sin título)"),
            "description": event.get("description", ""),
            "location": event.get("location", ""),
            "start": start.get("dateTime", start.get("date", "")),
            "end": end.get("dateTime", end.get("date", "")),
            "allDay": "date" in start and "dateTime" not in start,
            "status": event.get("status", ""),
            "organizer": event.get("organizer", {}).get("email", ""),
            "attendees": attendees,
            "attendeeCount": len(attendees),
            "meetLink": event.get("hangoutLink", ""),
            "htmlLink": event.get("htmlLink", ""),
            "recurrence": bool(event.get("recurrence") or event.get("recurringEventId")),
        }
