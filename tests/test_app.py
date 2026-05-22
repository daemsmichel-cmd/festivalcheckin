import io
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import create_app, resolve_local_ssl_context


class FestivalFinderTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.upload_root = root / "uploads"

        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(root / "test.db"),
                "UPLOAD_ROOT": str(self.upload_root),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login_admin(self, next_url: str = "/?tab=manage"):
        response = self.client.post(
            "/admin/login",
            data={
                "username": self.app.config["ADMIN_USERNAME"],
                "password": self.app.config["ADMIN_PASSWORD"],
                "next": next_url,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        return response

    def logout_admin(self):
        response = self.client.post("/admin/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        return response

    def test_homepage_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Festival Finder", response.data)
        self.assertNotIn(
            b"Scroll sideways, then open a band to check in and see everyone\xe2\x80\x99s photos and position.",
            response.data,
        )
        self.assertIn(b"/static/js/timetable_overview.js", response.data)
        self.assertIn(b"Admin login", response.data)
        self.assertNotIn(b'href="/?tab=manage"', response.data)
        self.assertNotIn(b"bands tracked", response.data)
        self.assertNotIn(b"friend check-ins", response.data)
        self.assertNotIn(b"photos per check-in", response.data)

    def test_railway_volume_mount_path_is_used_as_default_data_root(self):
        with tempfile.TemporaryDirectory() as volume_root:
            with patch.dict(os.environ, {"RAILWAY_VOLUME_MOUNT_PATH": volume_root}, clear=False):
                app = create_app(
                    {
                        "TESTING": True,
                        "SECRET_KEY": "test-secret",
                    }
                )

        self.assertEqual(app.config["DATABASE"], str(Path(volume_root) / "festival_finder.db"))
        self.assertEqual(app.config["UPLOAD_ROOT"], str(Path(volume_root) / "uploads"))

    def test_admin_login_and_logout_toggle_manage_access(self):
        response = self.client.get("/?tab=manage")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Excel CSV import", response.data)

        login_response = self.login_admin()
        self.assertIn("/?tab=manage", login_response.headers["Location"])

        manage_response = self.client.get("/?tab=manage")
        self.assertEqual(manage_response.status_code, 200)
        self.assertIn(b"Excel CSV import", manage_response.data)
        self.assertIn(b"Log out", manage_response.data)

        self.logout_admin()
        logged_out_response = self.client.get("/?tab=manage")
        self.assertEqual(logged_out_response.status_code, 200)
        self.assertNotIn(b"Excel CSV import", logged_out_response.data)

    def test_non_admin_is_redirected_to_admin_login_for_manage_routes(self):
        response = self.client.post(
            "/bands",
            data={
                "band_name": "Blocked Route",
                "festival_name": "North Field",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

    def test_homepage_groups_bands_by_stage_and_time(self):
        self.login_admin()
        first_response = self.client.post(
            "/bands",
            data={
                "band_name": "North Skyline",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "21:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(first_response.status_code, 302)

        second_response = self.client.post(
            "/bands",
            data={
                "band_name": "Late Echo",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "20:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(second_response.status_code, 302)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Main Stage", response.data)
        self.assertIn(b"Tent Stage", response.data)
        self.assertIn(b"Wednesday, 19 Aug 2026", response.data)
        self.assertIn(b"10:30", response.data)
        self.assertIn(b"04:00", response.data)
        self.assertIn(b'data-schedule-date="2026-08-19"', response.data)
        self.assertIn(b'data-day-start-minutes="630"', response.data)
        self.assertIn(b'data-day-end-minutes="1680"', response.data)
        self.assertIn(b'data-pixels-per-minute="3"', response.data)
        self.assertEqual(response.data.count(b"schedule-row__label"), 2)
        self.assertIn(b"left: 1710px; width: 180px;", response.data)
        self.assertIn(b"left: 1710px; width: 90px;", response.data)
        self.assertNotIn(b"schedule-band schedule-band--active", response.data)

    def test_homepage_places_after_midnight_bands_at_end_of_festival_day(self):
        self.login_admin()
        late_response = self.client.post(
            "/bands",
            data={
                "band_name": "Late Sparks",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "23:30",
                "end_time": "00:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(late_response.status_code, 302)

        after_midnight_response = self.client.post(
            "/bands",
            data={
                "band_name": "Night Bloom",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-19",
                "start_time": "01:00",
                "end_time": "02:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(after_midnight_response.status_code, 302)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"23:30", response.data)
        self.assertIn(b"00:30", response.data)
        self.assertIn(b"01:00", response.data)
        self.assertIn(b"02:00", response.data)
        self.assertIn(b"left: 2340px; width: 180px;", response.data)
        self.assertIn(b"left: 2610px; width: 180px;", response.data)

    def test_import_csv_from_excel_export(self):
        self.login_admin()
        response = self.client.post(
            "/bands/import",
            data={
                "festival_name": "North Field",
                "performance_date": "2026-08-19",
                "timetable_import_file": (
                    io.BytesIO(
                        (
                            "Stage;Start;End;Band Name\n"
                            "Main Stage;20:00;21:00;North Skyline\n"
                            "Tent Stage;20:30;21:15;Late Echo\n"
                        ).encode("utf-8")
                    ),
                    "timetable.csv",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Imported 2 bands from the timetable file.", response.data)
        self.assertIn(b"Main Stage", response.data)
        self.assertIn(b"Tent Stage", response.data)

        overview_response = self.client.get("/")
        self.assertEqual(overview_response.status_code, 200)
        self.assertIn(b"North Skyline", overview_response.data)
        self.assertIn(b"Late Echo", overview_response.data)

    def test_create_band_and_attendee_checkin(self):
        self.login_admin()
        response = self.client.post(
            "/bands",
            data={
                "band_name": "The Twilight Set",
                "festival_name": "North Field",
                "stage_name": "River Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:30",
                "end_time": "21:45",
                "timetable_notes": "Meet by the sound tower after the set.",
                "timetable_file": (io.BytesIO(b"fake timetable"), "timetable.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The Twilight Set", response.data)
        self.assertIn(b"Photos and positions", response.data)
        self.assertNotIn(b"Friend map", response.data)
        self.assertIn(b"Delete band", response.data)
        self.assertNotIn(b"Latitude", response.data)
        self.assertNotIn(b"Longitude", response.data)
        self.assertNotIn(b"Add your crowd view", response.data)
        self.assertNotIn(b"Share a name, GPS location, POV photo, and side photo.", response.data)
        self.assertNotIn(b"Tap once to add your position before checking in.", response.data)
        self.assertNotIn(b"iPhone only allows browser location on HTTPS sites.", response.data)

        self.logout_admin()
        timeline_response = self.client.get("/")
        self.assertEqual(timeline_response.status_code, 200)
        self.assertIn(b"Swipe or scroll horizontally to move through the lineup.", timeline_response.data)

        response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Michel",
                "latitude": "51.234567",
                "longitude": "4.123456",
                "note": "Front-left barrier, close to the camera rail.",
                "pov_image": (io.BytesIO(b"pov image"), "pov.jpg"),
                "side_image": (io.BytesIO(b"side image"), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Michel", response.data)
        self.assertIn(b"Checked in just now", response.data)
        self.assertTrue(any(self.upload_root.joinpath("attendees").iterdir()))

        overview_response = self.client.get("/")
        self.assertEqual(overview_response.status_code, 200)
        self.assertIn(b"schedule-band schedule-band--active", overview_response.data)
        self.assertNotIn(b"Manage timetable", overview_response.data)

        api_response = self.client.get("/api/bands/1/attendees")
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.get_json()
        self.assertEqual(payload["attendees"][0]["display_name"], "Michel")
        self.assertIn("https://www.openstreetmap.org/", payload["attendees"][0]["map_url"])
        self.assertIn("https://maps.apple.com/?daddr=", payload["attendees"][0]["directions_url"])
        self.assertIn("maps://?daddr=", payload["attendees"][0]["ios_app_directions_url"])

        band_detail_response = self.client.get("/bands/1")
        self.assertEqual(band_detail_response.status_code, 200)
        self.assertIn(b"Open map", band_detail_response.data)
        self.assertIn(b"Exit crowd", band_detail_response.data)

        other_client = self.app.test_client()
        other_band_detail_response = other_client.get("/bands/1")
        self.assertEqual(other_band_detail_response.status_code, 200)
        self.assertNotIn(b"Exit crowd", other_band_detail_response.data)

        other_delete_response = other_client.post(
            "/bands/1/attendees/1/delete",
            follow_redirects=True,
        )
        self.assertEqual(other_delete_response.status_code, 200)
        self.assertIn(b"You can only remove your own check-in.", other_delete_response.data)

        delete_response = self.client.post(
            "/bands/1/attendees/1/delete",
            follow_redirects=True,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"left the crowd", delete_response.data)
        self.assertIn(b"No one has checked in yet", delete_response.data)
        self.assertFalse(any(self.upload_root.joinpath("attendees").iterdir()))

        api_response = self.client.get("/api/bands/1/attendees")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.get_json(), {"attendees": []})

    def test_relative_time_label_for_older_checkins(self):
        self.login_admin()
        create_response = self.client.post(
            "/bands",
            data={
                "band_name": "Slow Echo",
                "festival_name": "North Field",
                "performance_date": "2026-08-20",
                "start_time": "18:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        self.logout_admin()
        attendee_response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Ari",
                "latitude": "50.850300",
                "longitude": "4.351700",
                "pov_image": (io.BytesIO(b"pov image"), "pov.jpg"),
                "side_image": (io.BytesIO(b"side image"), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(attendee_response.status_code, 302)

        older_time = (datetime.now(UTC) - timedelta(hours=2, minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        db = sqlite3.connect(self.app.config["DATABASE"])
        db.execute("UPDATE attendees SET created_at = ? WHERE id = 1", (older_time,))
        db.commit()
        db.close()

        response = self.client.get("/bands/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Checked in 2 hrs ago", response.data)

    def test_delete_stage_removes_all_bands_on_that_lane(self):
        self.login_admin()
        first_band = self.client.post(
            "/bands",
            data={
                "band_name": "North Skyline",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "21:00",
                "timetable_file": (io.BytesIO(b"fake timetable"), "timetable.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(first_band.status_code, 302)

        second_band = self.client.post(
            "/bands",
            data={
                "band_name": "Midnight Current",
                "festival_name": "North Field",
                "stage_name": "Main Stage",
                "performance_date": "2026-08-19",
                "start_time": "21:15",
                "end_time": "22:00",
            },
            follow_redirects=False,
        )
        self.assertEqual(second_band.status_code, 302)

        third_band = self.client.post(
            "/bands",
            data={
                "band_name": "Tent Echo",
                "festival_name": "North Field",
                "stage_name": "Tent Stage",
                "performance_date": "2026-08-19",
                "start_time": "20:00",
                "end_time": "20:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(third_band.status_code, 302)

        attendee_response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Mila",
                "latitude": "50.850300",
                "longitude": "4.351700",
                "pov_image": (io.BytesIO(b"pov image"), "pov.jpg"),
                "side_image": (io.BytesIO(b"side image"), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(attendee_response.status_code, 302)
        self.assertTrue(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertTrue(any(self.upload_root.joinpath("attendees").iterdir()))

        delete_response = self.client.post(
            "/stages/delete",
            data={
                "performance_date": "2026-08-19",
                "festival_name": "North Field",
                "stage_name_value": "Main Stage",
            },
            follow_redirects=True,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"Main Stage on 2026-08-19 was deleted from North Field.", delete_response.data)
        self.assertIn(b"Tent Stage", delete_response.data)
        self.assertEqual(self.client.get("/bands/1").status_code, 404)
        self.assertEqual(self.client.get("/bands/2").status_code, 404)
        self.assertEqual(self.client.get("/bands/3").status_code, 200)
        self.assertFalse(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertFalse(any(self.upload_root.joinpath("attendees").iterdir()))

    def test_delete_band_removes_band_and_uploaded_files(self):
        self.login_admin()
        create_response = self.client.post(
            "/bands",
            data={
                "band_name": "Midnight Parade",
                "festival_name": "North Field",
                "stage_name": "Lake Stage",
                "performance_date": "2026-08-21",
                "start_time": "22:00",
                "timetable_file": (io.BytesIO(b"fake timetable"), "timetable.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        attendee_response = self.client.post(
            "/bands/1/attendees",
            data={
                "display_name": "Nina",
                "latitude": "50.850300",
                "longitude": "4.351700",
                "pov_image": (io.BytesIO(b"pov image"), "pov.jpg"),
                "side_image": (io.BytesIO(b"side image"), "side.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(attendee_response.status_code, 302)
        self.assertTrue(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertTrue(any(self.upload_root.joinpath("attendees").iterdir()))

        delete_response = self.client.post("/bands/1/delete", follow_redirects=True)
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"Midnight Parade was deleted.", delete_response.data)
        self.assertIn(b"No bands added yet", delete_response.data)
        self.assertFalse(any(self.upload_root.joinpath("timetables").iterdir()))
        self.assertFalse(any(self.upload_root.joinpath("attendees").iterdir()))
        self.assertEqual(self.client.get("/bands/1").status_code, 404)

    def test_resolve_local_ssl_context_uses_default_dev_cert_paths(self):
        cert_dir = Path(self.temp_dir.name) / "certs"
        cert_dir.mkdir()
        cert_path = cert_dir / "dev-cert.pem"
        key_path = cert_dir / "dev-key.pem"
        cert_path.write_text("cert", encoding="utf-8")
        key_path.write_text("key", encoding="utf-8")

        with patch.dict(os.environ, {"LOCAL_HTTPS": "1"}, clear=False):
            ssl_context = resolve_local_ssl_context(self.temp_dir.name)

        self.assertEqual(ssl_context, (str(cert_path), str(key_path)))

    def test_resolve_local_ssl_context_returns_none_when_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_local_ssl_context(self.temp_dir.name))


if __name__ == "__main__":
    unittest.main()
