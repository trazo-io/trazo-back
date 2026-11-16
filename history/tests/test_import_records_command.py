"""`import_records`: dry run, the filed preview, and a commit that writes only what the grower saw."""

import hashlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from pdfminer.high_level import extract_text

from documents.models import GeneratedDocument
from history.models import ChemicalEvent
from history.services import record_intake
from history.services.record_intake import COLUMNS
from history.tests.test_record_intake import FIXTURE, IntakeFarm, _all_records, _csv


class ImportRecordsCommandTests(IntakeFarm):
    def _file(self, text=None):
        text = (text or FIXTURE.read_text(encoding="utf-8")).replace("{DOC}", str(self.doc.public_id))
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        return handle.name

    def _run(self, path, *extra, created_by=None):
        out = io.StringIO()
        call_command(
            "import_records",
            "--file",
            path,
            "--farm",
            str(self.farm.id),
            "--created-by",
            created_by or self.operator.email,
            *extra,
            stdout=out,
        )
        return out.getvalue()

    def test_dry_run_writes_nothing_and_renders_the_preview(self):
        out_pdf = Path(tempfile.mkdtemp()) / "preview.pdf"
        text = self._run(self._file(), "--preview-out", str(out_pdf))
        self.assertIn("DRY RUN", text)
        self.assertIn("15 rows → 26 records · 5 rows wait", text)
        self.assertIn("setup operator: yes", text)
        self.assertIn("- sheet row 9: date 'mid May' is not YYYY-MM-DD", text)
        self.assertIn("- sheet row 14: no parcel named 'fence line N'", text)
        self.assertIn("optional columns: none", text)
        self.assertEqual(_all_records(self.farm), [])
        self.assertEqual(GeneratedDocument.objects.filter(source="import_preview").count(), 0)

        flat = " ".join(extract_text(io.BytesIO(out_pdf.read_bytes())).split())
        self.assertIn("Nothing has been saved", flat)
        self.assertIn("Spray and field log 2026", flat)
        self.assertIn("sheet row 3", flat)
        self.assertIn("mid May", flat)
        self.assertIn("4 records, one per block", flat)
        self.assertNotIn("SPECIMEN", flat, "a real farm's preview is never marked as fabricated")

    def test_a_demo_farm_preview_is_marked_specimen(self):
        self.farm.is_demo = True
        self.farm.save(update_fields=["is_demo"])
        out_pdf = Path(tempfile.mkdtemp()) / "preview.pdf"
        self._run(self._file(), "--preview-out", str(out_pdf))
        self.assertIn("SPECIMEN", extract_text(io.BytesIO(out_pdf.read_bytes())))

    def test_file_preview_files_one_undeletable_document_with_the_batch_tag(self):
        path = self._file()
        text = self._run(path, "--file-preview")
        batch = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
        self.assertIn(f"batch {batch}", text)
        doc = GeneratedDocument.objects.get(source="import_preview")
        self.assertIn(f"import-batch:{batch}", doc.tags)
        self.assertFalse(doc.is_deletable)
        self.assertEqual(doc.folder, "exports")
        self.assertEqual(doc.created_by_id, self.operator.id)
        self.assertEqual(doc.establishment_id, self.farm.id)

    def test_commit_refuses_without_the_filed_preview_of_the_same_file(self):
        path = self._file()
        with self.assertRaises(CommandError) as ctx:
            self._run(path, "--commit")
        self.assertIn("No filed preview", str(ctx.exception))
        self.assertEqual(_all_records(self.farm), [])

        self._run(path, "--file-preview")
        # One changed cell is a different file, so a different batch: the grower saw the other one.
        changed = self._file(FIXTURE.read_text(encoding="utf-8").replace("dormant spray", "dormant spray, two passes"))
        with self.assertRaises(CommandError):
            self._run(changed, "--commit")
        self.assertEqual(_all_records(self.farm), [])

        text = self._run(path, "--commit")
        self.assertIn("26 records written, 5 rows waiting", text)
        self.assertEqual(len(_all_records(self.farm)), 26)

    def test_commit_refuses_when_the_farm_changed_since_the_preview(self):
        """The file is unchanged, but the farm now has the parcel a refused row named: the row
        would load, and the grower never saw it loading. The preview must be re-filed."""
        from history.models import Production
        from product.models import Parcel

        path = self._file()
        self._run(path, "--file-preview")
        fence = Parcel.objects.create(name="fence line N", establishment=self.farm, area=0.2)
        Production.objects.create(name="2026 fence", parcel=fence, product=self.product)
        with self.assertRaises(CommandError) as ctx:
            self._run(path, "--commit")
        self.assertIn("changed since the preview", str(ctx.exception))
        self.assertEqual(_all_records(self.farm), [])

        # The new parcel also joins the two "All" rows (4 blocks became 5), which is exactly what
        # the grower has to see again: 26 + 1 (the Roundup row) + 2 (the two All rows) = 29.
        self._run(path, "--file-preview")
        text = self._run(path, "--commit")
        self.assertIn("fence line N (5 records, shared group)", text)
        self.assertIn("29 records written, 4 rows waiting", text)

    def test_commit_is_all_or_nothing(self):
        path = self._file()
        self._run(path, "--file-preview")
        real = record_intake.write_record
        calls = {"n": 0}

        def fifth_write_fails(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 5:
                raise RuntimeError("disk full")
            return real(*args, **kwargs)

        with patch("history.services.record_intake.write_record", side_effect=fifth_write_fails):
            with self.assertRaises(RuntimeError):
                self._run(path, "--commit")
        self.assertEqual(calls["n"], 5)
        self.assertEqual(_all_records(self.farm), [], "four records written before the failure must be rolled back")

    def test_created_by_must_be_a_member_of_the_farms_company(self):
        stranger = get_user_model().objects.create_user(email="stranger@example.com", password="pw-for-tests-only")
        with self.assertRaises(CommandError) as ctx:
            self._run(self._file(), created_by=stranger.email)
        self.assertIn("not a member", str(ctx.exception))
        with self.assertRaises(CommandError):
            self._run(self._file(), created_by="nobody@example.com")

    def test_a_prohibited_row_is_flagged_in_the_dry_run(self):
        row = self.row(kind="herbicide", product="Roundup", active_ingredient="Glyphosate", target="weeds")
        text = self._run(self._file(_csv(row)))
        self.assertIn("WARNING", text)
        self.assertIn("Glyphosate, § 205.105, prohibited", text)
        self.assertEqual(_all_records(self.farm), [])

    def test_a_file_in_the_wrong_schema_is_refused_whole(self):
        with self.assertRaises(CommandError) as ctx:
            self._run(self._file("Date,Block,What\n3/14/2026,All,dormant spray\n"))
        self.assertIn("Not the intake schema", str(ctx.exception))


class SprayColumnsCommandTests(IntakeFarm):
    """The spray record columns through the command: the dry run and the preview say which optional
    columns were read and show what each record will hold; the commit writes one tank."""

    _file = ImportRecordsCommandTests._file
    _run = ImportRecordsCommandTests._run

    #: The spray columns this sheet has, with headers as an operator's spreadsheet spells them.
    SPELLED = {
        "epa_reg_no": "EPA Reg. No.",
        "wind_from": "Wind Direction",
        "wind_speed_mph": "Wind speed (mph)",
        "tank": "Tank ID",
        "tank_role": "tank_role",
    }

    def _spray_csv(self):
        columns = list(COLUMNS) + list(self.SPELLED)
        common = dict(date="2026-05-20", parcel="Block 2", tank="T1", wind_from="NW", wind_speed_mph="4")
        rows = [
            self.row(
                **common,
                product="Entrust SC",
                active_ingredient="Spinosad",
                rate="6",
                rate_unit="fl_oz_ac",
                target="codling moth",
                epa_reg_no="62719-621",
                source_locator="sheet row 7",
            ),
            self.row(
                **common,
                kind="fungicide",
                product="Kocide 3000-O",
                active_ingredient="Copper hydroxide",
                rate="2",
                rate_unit="lb_ac",
                target="fire blight",
                source_locator="sheet row 8",
            ),
            self.row(
                **common,
                product="Dyne-Amic",
                active_ingredient="",
                rate="",
                rate_unit="",
                target="",
                tank_role="adjuvant",
                source_locator="sheet row 9",
            ),
        ]
        body = _csv(*rows, columns=columns).split("\n", 1)[1]
        return ",".join(self.SPELLED.get(c, c) for c in columns) + "\n" + body

    def test_the_dry_run_and_the_preview_name_the_spray_columns_and_the_tank(self):
        out_pdf = Path(tempfile.mkdtemp()) / "preview.pdf"
        text = self._run(self._file(self._spray_csv()), "--preview-out", str(out_pdf))
        self.assertIn(
            "optional columns: epa_reg_no (as 'EPA Reg. No.'), wind_from (as 'Wind Direction'), "
            "wind_speed_mph (as 'Wind speed (mph)'), tank (as 'Tank ID'), tank_role",
            text,
        )
        self.assertIn("+ sheet row 7:", text)
        self.assertIn("(tank T1, line 1 of 3)", text)
        self.assertIn("(tank T1, line 3 of 3, adjuvant)", text)
        self.assertIn("3 rows → 3 records · 0 rows wait", text)

        flat = " ".join(extract_text(io.BytesIO(out_pdf.read_bytes())).split())
        self.assertIn("Spray record columns read from this file: epa_reg_no", flat)
        self.assertIn("tank T1: line 3 of 3, adjuvant", flat)
        self.assertIn("time: not on the source record", flat)
        self.assertIn("wind: from NW at 4 mph", flat)
        self.assertIn("EPA reg. no.: 62719-621", flat)
        self.assertEqual(_all_records(self.farm), [])

    def test_the_commit_writes_one_tank_and_a_second_commit_writes_nothing(self):
        path = self._file(self._spray_csv())
        self._run(path, "--file-preview")
        text = self._run(path, "--commit")
        self.assertIn("3 records written, 0 rows waiting", text)
        lines = list(ChemicalEvent.objects.order_by("tank_mix_line"))
        self.assertEqual([e.tank_mix_line for e in lines], [1, 2, 3])
        self.assertEqual(len({e.tank_mix_group for e in lines}), 1)
        self.assertEqual(lines[0].epa_registration_number, "62719-621")
        self.assertEqual({e.wind_from for e in lines}, {"NW"})

        # Same file again: the rows are already recorded, so the plan differs and needs its preview;
        # once filed, the commit writes nothing and never a second tank.
        with self.assertRaises(CommandError):
            self._run(path, "--commit")
        self._run(path, "--file-preview")
        self.assertIn("0 records written, 3 rows waiting", self._run(path, "--commit"))
        self.assertEqual(ChemicalEvent.objects.count(), 3)
