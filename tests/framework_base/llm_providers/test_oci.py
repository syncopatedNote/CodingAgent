import unittest
from unittest.mock import patch, MagicMock
from framework_base.llm_providers.oci import OCIProvider
from framework_base.llm_base import LLMFactory
from settings import settings

class TestOCIProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_key = settings.oci_api_key
        cls.compartment_id = settings.oci_compartment_id
        cls.region = settings.oci_region

    @patch('framework_base.llm_providers.oci.OCIProvider._create_client')
    def test_create_oci_provider(self, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        oci_provider = OCIProvider(
            api_key=self.api_key,
            compartment_id=self.compartment_id,
            region=self.region
        )

        mock_create_client.assert_called_once_with(self.api_key)
        self.assertEqual(oci_provider.client, mock_client)

    @patch('framework_base.llm_providers.oci.OCIProvider._create_client')
    def test_create_llm_factory_oci(self, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        llm = LLMFactory.create_llm(
            provider='oci',
            model_name='default_model',
            temperature=0.3
        )

        mock_create_client.assert_called_once_with(self.api_key)
        self.assertIsInstance(llm, OCIProvider)

    @patch('framework_base.llm_providers.oci.OCIProvider.invoke')
    def test_invoke_oci_provider(self, mock_invoke):
        mock_response = MagicMock()
        mock_response.json.return_value = {'output': 'test'}
        mock_invoke.return_value = mock_response

        oci_provider = OCIProvider(
            api_key=self.api_key,
            compartment_id=self.compartment_id,
            region=self.region
        )

        output = oci_provider.invoke(prompt="test prompt")
        mock_invoke.assert_called_once_with("test prompt")
        self.assertEqual(output, 'test')

if __name__ == '__main__':
    unittest.main()
```

### Explanation:
1. **File Location**: The file is placed in `tests/framework_base/llm_providers/test_oci.py` as per the feedback.
2. **Imports**: Imported necessary modules and classes for testing.
3. **Setup**: Set up class-level variables for the OCI API key, compartment ID, and region.
4. **Test Cases**:
    - `test_create_oci_provider`: Tests the creation of the OCI provider.
    - `test_create_llm_factory_oci`: Tests the creation of the OCI LLM via the factory.
    - `test_invoke_oci_provider`: Tests the invocation method of the OCI provider.
5. **Mocking**: Used `patch` and `MagicMock` to mock the client creation and invocation methods.
6. **Assertions**: Ensured the methods are called correctly and return the expected values.
7. **Run Tests**: Added the `if __name__ == '__main__': unittest.main()` block to run the tests.