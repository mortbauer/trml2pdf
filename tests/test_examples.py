import os
import io
import unittest

from six import text_type

from pathlib import Path
import trml2pdf  # dev mode: python setup.py develop


ROOT_DIR = Path(__file__).parent.parent
EXAMPLES_DIR = ROOT_DIR / "examples"


# sys.path.append(EXAMPLES_DIR)

class Test(unittest.TestCase):
    """run pdf genration using all files in examples."""

    def test_run_all(self):
        try:

            # change current dir, there are relative references to images in rmls
            work_dir = os.getcwd()
            os.chdir(EXAMPLES_DIR)
            self._run_all_examples()
        finally:
            os.chdir(work_dir)

    def _run_all_examples(self):
        for name in os.listdir('.'):
            if name.endswith(".rml"):
                path = name  # '{}/{}'.format(EXAMPLES_DIR, name)
                print('running: {}'.format(path))
                with open(path,'rb') as inputfile:
                    doc = trml2pdf.RMLDoc(inputfile.read(),path)
                    output = io.BytesIO()
                    doc.render(output)
                    self.assertIsNotNone(output.getvalue())


if __name__ == "__main__":
    unittest.main()
