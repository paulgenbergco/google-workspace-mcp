from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gapi import RETRIES


class CalendarService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("calendar", "v3", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ calendars

    def list_calendars(self) -> List[Dict[str, Any]]:
        result = self.service.calendarList().list().execute(num_retries=RETRIES)
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
        page_token: Optional[str] = None,
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
        if page_token:
            params["pageToken"] = page_token

        result = self.service.events().list(**params).execute(num_retries=RETRIES)
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
        page_token: Optional[str] = None,
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
        if page_token:
            params["pageToken"] = page_token

        result = self.service.events().list(**params).execute(num_retries=RETRIES)
        events = [self._parse_event(e) for e in result.get("items", [])]
        return {
            "query": query,
            "count": len(events),
            "events": events,
            "nextPageToken": result.get("nextPageToken"),
        }

    def get_event(self, event_id: str, calendar_id: str = "primary") -> Dict[str, Any]:
        event = self.service.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute(num_retries=RETRIES)
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
        recurrence: Optional[List[str]] = None,
        reminders: Optional[List[Dict[str, Any]]] = None,
        visibility: Optional[str] = None,
        color_id: Optional[str] = None,
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
        if recurrence:
            event_body["recurrence"] = recurrence
        if reminders is not None:
            event_body["reminders"] = {"useDefault": False, "overrides": reminders}
        if visibility:
            event_body["visibility"] = visibility
        if color_id:
            event_body["colorId"] = color_id

        params: Dict[str, Any] = {
            "calendarId": calendar_id,
            "body": event_body,
            "sendUpdates": "all",
        }
        if add_meet:
            params["conferenceDataVersion"] = 1

        result = self.service.events().insert(**params).execute(num_retries=RETRIES)
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
        recurrence: Optional[List[str]] = None,
        reminders: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Update fields on an existing event via PATCH (only provided fields)."""
        body: Dict[str, Any] = {}

        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if start is not None:
            if len(start) == 10 and "T" not in start:
                body["start"] = {"date": start}
            else:
                body["start"] = {"dateTime": start}
        if end is not None:
            if len(end) == 10 and "T" not in end:
                body["end"] = {"date": end}
            else:
                body["end"] = {"dateTime": end}
        if attendees is not None:
            body["attendees"] = [{"email": e} for e in attendees]
        if recurrence is not None:
            body["recurrence"] = recurrence
        if reminders is not None:
            body["reminders"] = {"useDefault": False, "overrides": reminders}

        result = self.service.events().patch(
            calendarId=calendar_id, eventId=event_id, body=body, sendUpdates="all"
        ).execute(num_retries=RETRIES)
        return self._parse_event(result)

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> Dict[str, Any]:
        """Delete a calendar event."""
        self.service.events().delete(
            calendarId=calendar_id, eventId=event_id, sendUpdates="all"
        ).execute(num_retries=RETRIES)
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
        ).execute(num_retries=RETRIES)

        for attendee in event.get("attendees", []):
            if attendee.get("self"):
                attendee["responseStatus"] = response
                break

        result = self.service.events().update(
            calendarId=calendar_id, eventId=event_id, body=event, sendUpdates="all"
        ).execute(num_retries=RETRIES)
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
        result = self.service.freebusy().query(body=body).execute(num_retries=RETRIES)

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

    def quick_add(self, text: str, calendar_id: str = "primary") -> Dict[str, Any]:
        """Create an event from a natural-language string."""
        result = self.service.events().quickAdd(
            calendarId=calendar_id, text=text, sendUpdates="all"
        ).execute(num_retries=RETRIES)
        return self._parse_event(result)

    def move_event(
        self,
        event_id: str,
        destination_calendar_id: str,
        source_calendar_id: str = "primary",
    ) -> Dict[str, Any]:
        """Move an event from one calendar to another."""
        result = self.service.events().move(
            calendarId=source_calendar_id,
            eventId=event_id,
            destination=destination_calendar_id,
            sendUpdates="all",
        ).execute(num_retries=RETRIES)
        return self._parse_event(result)

    def list_instances(
        self,
        event_id: str,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 25,
    ) -> Dict[str, Any]:
        """List the instances of a recurring event."""
        params: Dict[str, Any] = {
            "calendarId": calendar_id,
            "eventId": event_id,
            "maxResults": min(max_results, 50),
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max

        result = self.service.events().instances(**params).execute(num_retries=RETRIES)
        instances = [self._parse_event(e) for e in result.get("items", [])]
        return {
            "event_id": event_id,
            "count": len(instances),
            "instances": instances,
        }

    # ------------------------------------------------------------------ calendar management

    def create_calendar(
        self,
        summary: str,
        description: str = "",
        time_zone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new secondary calendar."""
        body: Dict[str, Any] = {"summary": summary, "description": description}
        if time_zone:
            body["timeZone"] = time_zone

        result = self.service.calendars().insert(body=body).execute(num_retries=RETRIES)
        return {
            "calendarId": result.get("id", ""),
            "summary": result.get("summary", summary),
        }

    def delete_calendar(self, calendar_id: str) -> Dict[str, Any]:
        """Delete a secondary calendar."""
        self.service.calendars().delete(calendarId=calendar_id).execute(num_retries=RETRIES)
        return {"deleted": True, "calendar_id": calendar_id}

    def suggest_free_slots(
        self,
        emails: List[str],
        time_min: str,
        time_max: str,
        duration_minutes: int = 30,
        day_start_hour: int = 9,
        day_end_hour: int = 18,
        max_slots: int = 10,
    ) -> Dict[str, Any]:
        """Suggest open meeting slots across several people's calendars.

        Queries free/busy for all ``emails``, merges their busy intervals, and
        sweeps the [``time_min``, ``time_max``] window for gaps of at least
        ``duration_minutes``. Within each day, candidate times are restricted to
        [``day_start_hour``, ``day_end_hour``). NOTE: these hours are interpreted
        in UTC for simplicity, not in any local time zone.
        """

        def _parse(ts: str) -> datetime:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        result = self.service.freebusy().query(
            body={
                "timeMin": time_min,
                "timeMax": time_max,
                "items": [{"id": e} for e in emails],
            }
        ).execute(num_retries=RETRIES)

        # Merge all busy intervals across all calendars.
        busy: List[List[datetime]] = []
        for info in result.get("calendars", {}).values():
            for b in info.get("busy", []):
                busy.append([_parse(b["start"]), _parse(b["end"])])
        busy.sort(key=lambda iv: iv[0])

        merged: List[List[datetime]] = []
        for iv in busy:
            if merged and iv[0] <= merged[-1][1]:
                if iv[1] > merged[-1][1]:
                    merged[-1][1] = iv[1]
            else:
                merged.append([iv[0], iv[1]])

        window_start = _parse(time_min)
        window_end = _parse(time_max)
        duration = timedelta(minutes=duration_minutes)

        slots: List[Dict[str, str]] = []
        day = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= window_end and len(slots) < max_slots:
            day_lo = day.replace(hour=day_start_hour)
            day_hi = day.replace(hour=0) + timedelta(hours=day_end_hour)
            cursor = max(day_lo, window_start)
            day_limit = min(day_hi, window_end)

            while cursor + duration <= day_limit and len(slots) < max_slots:
                slot_end = cursor + duration
                # Find a busy interval overlapping [cursor, slot_end).
                conflict = None
                for b_start, b_end in merged:
                    if b_start < slot_end and b_end > cursor:
                        conflict = b_end
                        break
                if conflict is None:
                    slots.append(
                        {
                            "start": cursor.isoformat(),
                            "end": slot_end.isoformat(),
                        }
                    )
                    cursor = slot_end
                else:
                    cursor = conflict

            day = day + timedelta(days=1)

        return {
            "timeMin": time_min,
            "timeMax": time_max,
            "durationMinutes": duration_minutes,
            "slots": slots,
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
