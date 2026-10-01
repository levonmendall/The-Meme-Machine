from pathlib import Path
import shutil
import tempfile
import unittest

from certification.stage_e_native_v2.contract import ROOT,HERE,read,sha256
from certification.stage_e_native_v2.workflow import validate


class WorkflowTests(unittest.TestCase):
    def test_yaml_static_inputs_matrix_aggregation_and_immutable_actions(self):
        self.assertTrue(validate()['passed'])
    def test_missing_candidate_forwarding_wrong_matrix_and_moving_action_rejected(self):
        source=ROOT/'.github/workflows/stagee-native-qualification-v2-reusable.yml'
        for old,new in [('MM_EXPECTED_SHA: ${{ inputs.expected_sha }}','MM_EXPECTED_SHA: wrong'),
                        (', m1-completion]',']'),
                        ('actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683','actions/checkout@main')]:
            with self.subTest(mutation=old),tempfile.TemporaryDirectory() as td:
                root=Path(td);base=root/'.github/workflows';base.mkdir(parents=True)
                shutil.copy(ROOT/'.github/workflows/stagee-native-qualification-v2.yml',base)
                target=base/source.name;target.write_text(source.read_text().replace(old,new))
                directory=root/'certification/stage_e_native_v2';directory.mkdir(parents=True)
                shutil.copy(HERE/'trial-definition-v2.json',directory)
                with self.assertRaises(AssertionError):validate(root)
    def test_evidence_json_schema_is_valid_under_available_tooling(self):
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(read(HERE/'evidence-schema-v2.json'))


if __name__=='__main__':unittest.main()
