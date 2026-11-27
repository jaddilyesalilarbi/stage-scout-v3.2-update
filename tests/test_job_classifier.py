"""Behavioral cases: mission semantics, source evidence and conservative constraints."""
import copy
import importlib.util
import unittest


class ClassifierTests(unittest.TestCase):
    def classify(self, text="", title="Engineering intern", profile=None, **fields):
        self.assertIsNotNone(importlib.util.find_spec("job_classifier"),
                             "The pure job classifier has not been implemented")
        from job_classifier import classify
        return classify(dict(title=title, description=text, description_status="complete",
                             location="Paris, France", **fields), profile)

    def test_missing_missions_are_uncertain_even_with_promising_title(self):
        row = self.classify(title="R&D Mechanical Design Intern")
        self.assertEqual(row["pdm_potential"], "uncertain")
        self.assertTrue(row["missing_information"])
        self.assertTrue(row["needs_human_review"])

    def test_formal_thesis_and_mechanical_relevance_are_independent(self):
        row = self.classify("Tasks\nDevelop a new language model for text classification.",
                            title="Master Thesis - Natural language processing")
        self.assertEqual(row["pdm_potential"], "explicit")
        self.assertTrue(row["pdm_explicit"])
        self.assertLess(row["technical_score"], 35)

    def test_design_and_validation_of_a_system_offer_high_pdm_potential(self):
        row = self.classify("Your responsibilities\nDesign a composite gripper for a robotic arm.\n"
                            "Develop an experimental test rig to validate the prototype stiffness.")
        self.assertEqual(row["pdm_potential"], "high")
        self.assertIn("Mechanical Design", row["technical_categories"])
        self.assertIn("Testing / Validation", row["technical_categories"])
        self.assertGreaterEqual(row["technical_score"], 65)
        self.assertGreaterEqual(len(row["mission_evidence"]), 2)

    def test_routine_testing_in_rd_department_is_low(self):
        row = self.classify("About us\nOur R&D department designs innovative robotic systems.\n"
                            "Your tasks\nExecute routine tests according to existing procedures.\n"
                            "Update test reports and maintain the equipment inventory.")
        self.assertEqual(row["pdm_potential"], "low")
        self.assertNotIn("Mechanical Design", row["technical_categories"])

    def test_qualifications_do_not_become_missions(self):
        row = self.classify("Responsibilities\nUpdate the purchasing database and track deliveries.\n"
                            "Qualifications\nExperience designing mechanical systems and developing "
                            "experimental prototypes with finite element simulation is desirable.")
        self.assertEqual(row["pdm_potential"], "low")
        self.assertIn("Supply Chain / Logistics", row["technical_categories"])
        self.assertNotIn("Simulation / CAE", row["technical_categories"])
        self.assertLess(row["technical_score"], 35)

    def test_rd_context_and_keyword_lists_are_not_high(self):
        row = self.classify("We are a leader in R&D, innovation, simulation, CAD and robotics.")
        self.assertEqual(row["pdm_potential"], "uncertain")
        self.assertLess(row["technical_score"], 35)

    def test_one_engineering_design_mission_is_medium(self):
        row = self.classify("Tasks\nDesign a mechanical bracket using CAD.")
        self.assertEqual(row["pdm_potential"], "medium")

    def test_french_investigation_and_comparison_support_high(self):
        row = self.classify("Vos missions :\nÉtudier le comportement thermomécanique des composites.\n"
                            "Comparer les modèles éléments finis aux résultats expérimentaux pour valider les hypothèses.")
        self.assertEqual(row["pdm_potential"], "high")
        self.assertIn("Simulation / CAE", row["technical_categories"])
        self.assertIn("Materials / Processes", row["technical_categories"])

    def test_explicit_thesis_in_qualification_is_not_the_offered_thesis(self):
        row = self.classify("Tasks\nUpdate production dashboards.\nQualifications\n"
                            "Previous master thesis experience in simulation is a plus.")
        self.assertFalse(row["pdm_explicit"])
        self.assertEqual(row["pdm_potential"], "low")

    def test_french_final_project_offer_is_explicit(self):
        row = self.classify("Ce stage peut être réalisé dans le cadre d'un projet de master.\n"
                            "Missions\nConcevoir un banc d'essai mécanique.")
        self.assertEqual(row["pdm_potential"], "explicit")

    def test_negated_design_does_not_raise_routine_work(self):
        row = self.classify("Tasks\nYou will not design new systems.\n"
                            "Execute standard acceptance tests and update reports.")
        self.assertEqual(row["pdm_potential"], "low")

    def test_short_excerpt_is_not_confident_full_classification(self):
        row = self.classify("", description_excerpt="Design a mechanical fixture.")
        self.assertEqual(row["pdm_confidence"], "low")
        self.assertTrue(row["needs_human_review"])

    def test_source_snippets_are_verbatim_and_duplicates_cannot_inflate_score(self):
        text = "Design a mechanical bracket using CAD."
        single = self.classify(text)
        repeated = self.classify("\n".join([text] * 20))
        self.assertEqual(single["technical_score"], repeated["technical_score"])
        self.assertEqual(single["pdm_potential"], repeated["pdm_potential"])
        self.assertTrue(all(snippet in text for snippet in single["mission_evidence"]))

    def test_constraints_use_unknown_instead_of_inventing_applicant_skills(self):
        row = self.classify("Requirements\nFluent German is required.\nEU citizenship required.\n"
                            "Currently enrolled in a Master's degree in mechanical engineering.\n"
                            "Duration: 6 months. Start date: February 2027.")
        c = row["constraints"]
        for key in ("languages", "eligibility", "duration", "start_date"):
            self.assertEqual(c[key]["status"], "unknown", key)
            self.assertTrue(c[key]["evidence"], key)
        self.assertEqual(c["education"]["status"], "compatible")
        self.assertEqual(c["location"]["status"], "compatible")
        self.assertEqual(row["constraint_status"], "unknown")

    def test_only_explicit_phd_requirement_excludes_master_student(self):
        for phrase in ("Applicants must be enrolled in a PhD program.", "Doctorants uniquement."):
            with self.subTest(phrase=phrase):
                row = self.classify("Requirements\n" + phrase)
                self.assertEqual(row["constraints"]["education"]["status"], "incompatible")
                self.assertEqual(row["constraint_status"], "incompatible")
        for phrase in ("Master or PhD student.", "PhD preferred.", "Work alongside PhD researchers."):
            with self.subTest(phrase=phrase):
                self.assertNotEqual(self.classify(phrase)["constraints"]["education"]["status"], "incompatible")

    def test_known_languages_can_be_compared_but_optional_language_is_not_blocking(self):
        row = self.classify("Requirements\nGerman is required. French is a plus.",
                            profile={"languages": ["English", "French"]})
        self.assertEqual(row["constraints"]["languages"]["status"], "incompatible")
        row = self.classify("Requirements\nGerman is a plus.", profile={"languages": ["English"]})
        self.assertNotEqual(row["constraints"]["languages"]["status"], "incompatible")

    def test_profile_duration_is_compared_only_when_given(self):
        row = self.classify("Duration: 3 months.", profile={"duration_months": [5, 6]})
        self.assertEqual(row["constraints"]["duration"]["status"], "incompatible")
        self.assertEqual(self.classify("Duration: 3 months.")["constraints"]["duration"]["status"], "unknown")

    def test_duration_ranges_and_minimum_are_not_treated_as_exact(self):
        for phrase in ("Duration: 5 to 6 months.", "Duration: at least 5 months."):
            with self.subTest(phrase=phrase):
                row = self.classify(phrase, profile={"duration_months": [6, 6]})
                self.assertEqual(row["constraints"]["duration"]["status"], "compatible")

    def test_mention_of_prior_experience_is_not_an_internship_duration(self):
        row = self.classify("Requirements\nAt least 12 months of previous experience with CAD.",
                            profile={"duration_months": [5, 6]})
        self.assertEqual(row["constraints"]["duration"]["status"], "unknown")
        self.assertEqual(row["constraints"]["duration"]["evidence"], [])

    def test_existing_german_exclusion_is_honored_without_guessing_skills(self):
        row = self.classify("Requirements\nGerman is required.",
                            profile={"exclude_required_german": True, "excluded_languages": ["de"]})
        self.assertEqual(row["constraints"]["languages"]["status"], "incompatible")
        self.assertIn("filtre", row["constraints"]["languages"]["reason"])

    def test_language_levels_and_or_alternatives_are_conservative(self):
        row = self.classify("Requirements\nFluent English is required.", profile={"languages": {"en": "A1"}})
        self.assertNotEqual(row["constraints"]["languages"]["status"], "compatible")
        row = self.classify("Requirements\nEnglish or German is required.", profile={"languages": ["en"]})
        self.assertEqual(row["constraints"]["languages"]["status"], "compatible")

    def test_optional_german_in_same_sentence_does_not_trigger_exclusion(self):
        row = self.classify("Requirements\nFluent English is required, German is a plus.",
                            profile={"languages": ["en"], "exclude_required_german": True})
        self.assertEqual(row["constraints"]["languages"]["status"], "compatible")
        self.assertEqual(row["constraints"]["languages"]["value"], "en")

    def test_unheaded_company_and_qualification_sentences_are_not_tasks(self):
        for phrase in ("We design mechanical components and develop innovative prototypes.",
                       "A passion for designing mechanical systems and simulation is desirable."):
            with self.subTest(phrase=phrase):
                row = self.classify(phrase)
                self.assertEqual(row["pdm_potential"], "uncertain")

    def test_bare_generic_administration_is_low_not_a_system_design_project(self):
        row = self.classify("Tasks\nDevelop production reports and design project management dashboards.")
        self.assertEqual(row["pdm_potential"], "low")
        self.assertLess(row["technical_score"], 35)

    def test_nationality_text_without_requirement_is_not_an_exclusion(self):
        row = self.classify("We welcome applicants regardless of nationality.")
        self.assertEqual(row["constraints"]["eligibility"]["evidence"], [])

    def test_bachelor_only_and_nonengineering_masters_require_review(self):
        row = self.classify("Requirements\nA Master's degree in marketing is required.")
        self.assertNotEqual(row["constraints"]["education"]["status"], "compatible")

    def test_explicit_master_offer_in_plain_text(self):
        row = self.classify("This master thesis focuses on structural simulation of a composite beam.")
        self.assertTrue(row["pdm_explicit"])

    def test_curly_apostrophe_master_title_is_explicit(self):
        self.assertTrue(self.classify(title="Master’s Thesis – Mechanical Design")["pdm_explicit"])

    def test_unknown_constraints_are_explained_in_missing_information(self):
        row = self.classify("Tasks\nDesign a mechanical bracket using CAD.")
        self.assertTrue(any("durée" in text.lower() for text in row["missing_information"]))

    def test_company_heading_can_transition_to_explicit_role_missions(self):
        row = self.classify("About us\nWe develop robots.\nAs an intern, you will design a mechanical gripper.\n"
                            "You will develop an experimental test rig to validate the prototype.")
        self.assertEqual(row["pdm_potential"], "high")

    def test_html_headings_separate_company_and_mission(self):
        row = self.classify("<h2>About us</h2><p>We design robots.</p><h2>Tasks</h2>"
                            "<li>Update inventory reports.</li><h2>Requirements</h2><p>Experience with CAD.</p>")
        self.assertEqual(row["pdm_potential"], "low")
        self.assertNotIn("Robotics / Mechatronics", row["technical_categories"])

    def test_recruitment_sentence_is_not_research(self):
        row = self.classify("Nos experts en conception mécanique recherchent de nouveaux talents pour notre bureau d'études.")
        self.assertEqual(row["pdm_potential"], "uncertain")

    def test_inline_headings_preserve_cae_missions_and_exclude_knowledge(self):
        row = self.classify("About Us: We build ships. Responsibilities Design a new mechanical bogie. "
                            "Conduct finite element analysis and performance assessments. Education "
                            "Knowledge of CAD and robotics is required.")
        self.assertEqual(row["pdm_potential"], "high")
        self.assertIn("Simulation / CAE", row["technical_categories"])
        self.assertNotIn("Robotics / Mechatronics", row["technical_categories"])

    def test_digital_twin_supply_study_is_research_with_limited_mechanical_relevance(self):
        row = self.classify("Missions\nDéveloppement d'un jumeau numérique de Supply Chain.\n"
                            "La modélisation de fonctionnement d'un stockage.\n"
                            "L'optimisation de la configuration d'une Supply Chain.\n"
                            "Une revue de l'état de l'art et un bilan scientifique.")
        self.assertEqual(row["pdm_potential"], "high")
        self.assertLessEqual(row["technical_score"], 35)
        self.assertIn("Supply Chain / Logistics", row["technical_categories"])

    def test_software_procedures_for_hardware_are_development(self):
        row = self.classify("Your impact\nDevelop, test, and deploy automated test procedures for hardware subsystems.\n"
                            "Instrument and control hardware devices and sensors through software interfaces.")
        self.assertIn(row["pdm_potential"], ("medium", "high"))
        self.assertIn("Testing / Validation", row["technical_categories"])
        self.assertIn("Automation / Control", row["technical_categories"])

    def test_specs_and_industrialisation_are_not_product_design(self):
        row = self.classify("Missions\nDéfinition du cahier des charges des outils de production lors du processus de conception.\n"
                            "Caractérisation de nos outils de production et réalisation du cahier des charges.\n"
                            "Affectation des pièces et définition des modes d'approvisionnement.")
        self.assertEqual(row["pdm_potential"], "medium")
        self.assertIn("Supply Chain / Logistics", row["technical_categories"])

    def test_supporting_test_operations_with_infrastructure_work_is_medium(self):
        row = self.classify("Tasks\nSupport test campaigns on rocket motors.\n"
                            "Support definition and validation of instrumentation requirements.\n"
                            "Support development of test infrastructure and safety systems for rocket motor testing.")
        self.assertEqual(row["pdm_potential"], "medium")

    def test_automated_device_handling_is_a_physical_system(self):
        row = self.classify("Your new responsibilities The master thesis integrates mechanical and thermal handling requirements. "
                            "Develop an automated Device Under Test handling solution. "
                            "Automation of DUT transfer between trays and load boards. "
                            "Full automation including temperature-dependent measurement sequences. "
                            "Who we are looking for Students in mechatronics.", title="Master thesis")
        self.assertGreaterEqual(row["technical_score"], 50)
        self.assertIn("Robotics / Mechatronics", row["technical_categories"])
        self.assertIn("Testing / Validation", row["technical_categories"])

    def test_rhetorical_recruitment_and_daily_plan_build_are_not_research(self):
        row = self.classify("Job Description\nLooking for an opportunity to combine supply chain operations, business analysis, and transformation?\n"
                            "Tasks\nWork alongside supply planners on day-to-day topics: production plan build and updates.")
        self.assertEqual(row["pdm_potential"], "low")

    def test_material_law_work_and_production_workshops_are_categories(self):
        row = self.classify("Missions\nLe stage sera réalisé pour l'établissement des lois matériaux.")
        self.assertIn("Materials / Processes", row["technical_categories"])
        row = self.classify("Tasks\nLead problem-solving workshops with the production department.")
        self.assertIn("Manufacturing / Production", row["technical_categories"])

    def test_structuring_cost_models_is_not_structural_engineering(self):
        row = self.classify("Missions\nConcevoir et structurer les référentiels de coûts de la supply chain.\n"
                            "Modéliser les structures logistiques et comparer les scénarios de transport.")
        self.assertLess(row["technical_score"], 35)
        self.assertNotIn("Mechanical Design", row["technical_categories"])
        self.assertNotIn("Simulation / CAE", row["technical_categories"])

    def test_structured_repository_does_not_count_as_physical_structure(self):
        row = self.classify("Tasks\nMaintain a structured repository of supply planning processes.")
        self.assertLess(row["technical_score"], 15)

    def test_structured_locations_are_read_without_fabricating_missions(self):
        from job_classifier import classify
        for structured in ({"jobLocation": [{"address": {"addressLocality": "Toulouse", "addressCountry": "FR"}}]},
                           {"location": {"city": "Paris", "countryCode": "FR"}},
                           {"PrimaryLocation": "Paris, France"}):
            with self.subTest(structured=structured):
                row = classify({"title": "Intern", "structured": structured})
                self.assertEqual(row["constraints"]["location"]["status"], "compatible")
                self.assertEqual(row["pdm_potential"], "uncertain")

    def test_job_start_date_is_distinct_from_posting_and_expiry_dates(self):
        from job_classifier import classify
        row = classify({"structured": {"jobStartDate": "2027-02-01", "datePosted": "2026-10-20"}})
        self.assertIn("2027-02-01", row["constraints"]["start_date"]["value"])
        for key in ("datePosted", "validThrough", "startDate", "ExternalPostedStartDate"):
            with self.subTest(key=key):
                row = classify({"structured": {key: "2027-02-01"}})
                self.assertEqual(row["constraints"]["start_date"]["value"], "")

    def test_structured_language_is_document_language_not_a_skill_requirement(self):
        row = self.classify("", structured={"language": "de"}, profile={"exclude_required_german": True})
        self.assertEqual(row["constraints"]["languages"]["status"], "unknown")

    def test_explicit_structured_duration_can_be_compared(self):
        row = self.classify("", structured={"duration": "6 months"}, profile={"duration_months": [5, 6]})
        self.assertEqual(row["constraints"]["duration"]["status"], "compatible")

    def test_cae_can_describe_a_model_of_a_physical_product(self):
        row = self.classify("Tasks\nDevelop a simulation model of a product.\n"
                            "Validate the thermal behavior of the heat pump.")
        self.assertIn("Simulation / CAE", row["technical_categories"])

    def test_creo_parts_and_assemblies_are_mechanical_design(self):
        row = self.classify("Missions\nConcevoir et modéliser vos pièces et assemblages sur le logiciel CREO.")
        self.assertIn("Mechanical Design", row["technical_categories"])

    def test_no_profile_mutation_and_complete_contract(self):
        from job_classifier import classify, TECHNICAL_CATEGORIES
        job = {"title": "Intern", "description": "", "location": ""}
        profile = {"languages": ["French"]}
        before = copy.deepcopy((job, profile))
        row = classify(job, profile)
        self.assertEqual((job, profile), before)
        self.assertTrue(set(row["technical_categories"]) <= set(TECHNICAL_CATEGORIES))
        for constraint in row["constraints"].values():
            self.assertEqual(set(constraint), {"status", "value", "evidence", "reason"})
        self.assertEqual(set(row["constraints"]), {"duration", "start_date", "languages", "location", "education", "eligibility"})
        self.assertEqual(row, classify(job, profile))


if __name__ == "__main__":
    unittest.main()
