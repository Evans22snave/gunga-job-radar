"""Unit tests for kenya_jobs.py (no network, no database).

Run:  python -m unittest tests_kenya_jobs -v
"""

import unittest

from kenya_jobs import (
    classify_zone,
    evaluate_form4,
    form4_score,
    looks_remote,
    parse_myjobmag_detail,
    required_kcse_grade,
)


def job(title="", description="", location="Nairobi"):
    return {"title": title, "description": description, "location": location}


class RemoteGate(unittest.TestCase):

    def test_remote_in_title(self):
        self.assertTrue(looks_remote(job("Remote Customer Support Agent")))

    def test_wfh_in_location(self):
        self.assertTrue(looks_remote(job("Agent", location="Work from home")))

    def test_remote_areas_is_not_remote_job(self):
        self.assertFalse(looks_remote(job(
            "Field Officer", "Travel to remote areas of Turkana")))

    def test_fully_remote_description(self):
        self.assertTrue(looks_remote(job(
            "Data Annotator", "This is a fully remote position")))

    def test_work_from_anywhere(self):
        self.assertTrue(looks_remote(job(
            "Analyst", "You can work from anywhere in the world")))

    def test_onsite_job(self):
        self.assertFalse(looks_remote(job("Shop Attendant")))


class Form4(unittest.TestCase):

    def test_plain_shop_attendant_accepted(self):
        r = evaluate_form4(job(
            "Shop Attendant at Techzone",
            "Have strong communication skills and meet sales targets."))
        self.assertTrue(r.ok)
        self.assertEqual(r.level, "likely")

    def test_kcse_mentioned_is_confirmed(self):
        r = evaluate_form4(job(
            "Cleaner", "KCSE certificate holder. Must be hardworking."))
        self.assertTrue(r.ok)
        self.assertEqual(r.level, "confirmed")
        self.assertEqual(form4_score(r), 70)

    def test_kcse_certificate_is_not_an_extra_certificate(self):
        r = evaluate_form4(job(
            "Waiter", "Kenya Certificate of Secondary Education (KCSE) D plain."))
        self.assertTrue(r.ok)

    def test_county_support_staff_needs_computer_certificate(self):
        r = evaluate_form4(job(
            "Support Staff (4 Posts)",
            "Requirements for Appointment Kenya Certificate of Secondary "
            "Education mean (KCSE) D (Plain) Certificate in Computer "
            "Applications from a recognized institution."))
        self.assertFalse(r.ok)
        self.assertEqual(r.reject_reason, "extra certificate required")

    def test_diploma_required(self):
        r = evaluate_form4(job("Sales Rep", "Diploma in Sales and Marketing."))
        self.assertFalse(r.ok)

    def test_degree_required(self):
        r = evaluate_form4(job("Officer", "Bachelor's degree in Business."))
        self.assertFalse(r.ok)

    def test_driving_licence_required(self):
        r = evaluate_form4(job("Delivery Officer", "Valid driving licence class BCE."))
        self.assertFalse(r.ok)
        self.assertEqual(r.reject_reason, "licence required")

    def test_kcse_or_diploma_alternative_is_ok(self):
        r = evaluate_form4(job(
            "Receptionist", "KCSE or Diploma in Front Office."))
        self.assertTrue(r.ok)

    def test_diploma_as_advantage_is_ok(self):
        r = evaluate_form4(job(
            "Sales Agent", "KCSE. A diploma in marketing is an added advantage."))
        self.assertTrue(r.ok)

    def test_attach_copies_of_certificates_is_not_a_requirement(self):
        r = evaluate_form4(job(
            "Cleaner", "KCSE holder. Attach copies of your certificates."))
        self.assertTrue(r.ok)

    def test_grade_above_mine_rejected(self):
        r = evaluate_form4(job(
            "Clerk", "KCSE mean grade of B (plain) and above."))
        self.assertFalse(r.ok)
        self.assertIn("grade B", r.reject_reason)

    def test_grade_c_plain_accepted(self):
        r = evaluate_form4(job(
            "Clerk", "KCSE mean grade C (plain) or its equivalent."))
        self.assertTrue(r.ok)

    def test_grade_c_plus_rejected(self):
        r = evaluate_form4(job("Clerk", "KCSE mean grade of C+ (plus)."))
        self.assertFalse(r.ok)

    def test_lowercase_grade_phrase_without_grade_not_misread(self):
        self.assertIsNone(required_kcse_grade(
            "kcse with a minimum of two years experience"))

    def test_driver_titles_rejected_even_without_licence_text(self):
        for title in ("Driver", "Delivery Truck Driver (45k)", "Senior Driver"):
            r = evaluate_form4(job(title, "Deliver goods safely."))
            self.assertFalse(r.ok, title)

    def test_registered_with_body_rejected(self):
        r = evaluate_form4(job(
            "Assistant", "Must be registered with the Nursing Council."))
        self.assertFalse(r.ok)


class Detail(unittest.TestCase):

    HTML = """
    <html><body>
    <nav>Jobs by Education BA/BSc/HND Diploma KCSE Vocational</nav>
    <div>
      <h1>Shop Attendant at Generations Techzone</h1>
      <p>Posted: Oct 26, 2026</p>
      <h2>Shop Attendant</h2>
      <ul>
        <li>Job Type <a>Full Time</a> , <a>Onsite</a></li>
        <li>Qualification <a>Diploma</a> , <a>First School Leaving Certificate</a> , <a>KCSE</a></li>
        <li>Experience 1 year</li>
        <li>Location <a>Nairobi</a></li>
        <li>Job Field <a>Sales and Business Development</a></li>
      </ul>
      <p>Have strong communication skills.</p>
      <p><b>REQUIREMENTS</b></p>
      <ul><li>Basic math skills</li><li>Flexibility to work various shifts.</li></ul>
      <h2>Method of Application</h2>
      <p>Send your CV.</p>
    </div></body></html>
    """

    def test_parse(self):
        d = parse_myjobmag_detail(self.HTML)
        self.assertIn("KCSE", d["qualifications"])
        self.assertIn("Diploma", d["qualifications"])
        self.assertIn("Basic math skills", d["body"])
        self.assertNotIn("Diploma", d["body"])
        self.assertTrue(d["experience"].startswith("1 year"))

    def test_tags_do_not_trigger_blockers(self):
        d = parse_myjobmag_detail(self.HTML)
        r = evaluate_form4(job("Shop Attendant", "sales"), d)
        self.assertTrue(r.ok)
        self.assertEqual(r.level, "confirmed")

    def test_missing_structure_degrades_gracefully(self):
        d = parse_myjobmag_detail("<html><body>nothing</body></html>")
        self.assertEqual(d["qualifications"], [])
        self.assertEqual(d["body"], "")


class Zones(unittest.TestCase):

    def test_malindi(self):
        self.assertEqual(classify_zone("Malindi"), 0)

    def test_kilifi_county_towns(self):
        for town in ("Mtwapa", "Kilifi", "Watamu", "Mariakani"):
            self.assertEqual(classify_zone(town), 0, town)

    def test_mombasa_is_coast(self):
        self.assertEqual(classify_zone("Mombasa"), 1)

    def test_nairobi_and_estates(self):
        self.assertEqual(classify_zone("Nairobi"), 2)
        self.assertEqual(classify_zone("Kenya", "Cleaner - Lavington"), 2)

    def test_eldoret_and_narok(self):
        self.assertEqual(classify_zone("Eldoret"), 3)
        self.assertEqual(classify_zone("Narok"), 4)
        self.assertEqual(classify_zone("Maasai Mara"), 4)

    def test_nearest_wins_for_multi_location(self):
        self.assertEqual(classify_zone("Nairobi, Mombasa, Malindi"), 0)

    def test_unknown_town(self):
        self.assertEqual(classify_zone("Kericho"), 9)
        self.assertEqual(classify_zone("Kenya"), 9)

    def test_description_not_used(self):
        self.assertEqual(classify_zone("Kericho", "Support Staff"), 9)


if __name__ == "__main__":
    unittest.main()
