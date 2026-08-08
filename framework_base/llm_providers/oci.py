import logging
from typing import Dict, Optional

from langchain.llms.oci import OracleCloudInfrastructureLLM
from framework_base.llm_base import LLMFactory, BaseLLM

logger = logging.getLogger(__name__)

class OCIProvider(BaseLLM):
    """
    Oracle Cloud Infrastructure LLM provider class.
    """
    def __init__(self, api_key: str, compartment_id: str, model_name: str, temperature: float = 0.3):
        """
        Initialize the OCIProvider with required parameters.

        :param api_key: The API key for Oracle Cloud Infrastructure.
        :param compartment_id: The compartment ID for the OCI resources.
        :param model_name: The name of the OCI LLM model.
        :param temperature: The temperature for the model (default is 0.3).
        """
        self.api_key = api_key
        self.compartment_id = compartment_id
        self.model_name = model_name
        self.temperature = temperature
        self.llm = OracleCloudInfrastructureLLM(
            api_key=self.api_key,
            compartment_id=self.compartment_id,
            model_name=self.model_name,
            temperature=self.temperature
        )

    def generate(self, prompt: str) -> str:
        """
        Generate text using the OCI LLM model.

        :param prompt: The input prompt for the LLM.
        :return: The generated text.
        """
        try:
            response = self.llm.generate(prompt)
            return response
        except Exception as e:
            logger.error(f"Error generating text with OCI LLM: {e}")
            raise

def create_oci_provider(api_key: str, compartment_id: str, model_name: str, temperature: float = 0.3) -> OCIProvider:
    """
    Create an instance of the OCIProvider.

    :param api_key: The API key for Oracle Cloud Infrastructure.
    :param compartment_id: The compartment ID for the OCI resources.
    :param model_name: The name of the OCI LLM model.
    :param temperature: The temperature for the model (default is 0.3).
    :return: An instance of the OCIProvider.
    """
    return OCIProvider(api_key, compartment_id, model_name, temperature)

# Register the OCI provider in the LLMFactory
LLMFactory.register_provider("oci", create_oci_provider)
```

### `framework_base/llm_base.py`
```python
# Add the following import statement at the top of the file
from framework_base.llm_providers.oci import create_oci_provider

# Add the following line inside the LLMFactory class
providers_map = {
    #... other providers...
    "oci": create_oci_provider,
}

# Add the following line inside the LLMFactory.create_llm method
if provider_name == "oci":
    api_key = settings.oci_api_key
    compartment_id = settings.oci_compartment_id
    model_name = model_name
    temperature = temperature
    return OCIProvider(api_key, compartment_id, model_name, temperature)
```

### `settings.py`
```python
# Add the following environment variable declarations at the top of the file
OCI_API_KEY: str = Field(alias="OCI_API_KEY")
OCI_COMPARTMENT_ID: str = Field(alias="OCI_COMPARTMENT_ID")
```

### `tests/framework_base/llm_providers/test_oci_provider.py`
```python
import unittest
from framework_base.llm_providers.oci import create_oci_provider
from framework_base.settings import settings

class TestOCIProvider(unittest.TestCase):
    """
    Test cases for the OCIProvider class.
    """
    def setUp(self):
        """
        Set up the test environment.
        """
        settings.oci_api_key = "test_api_key"
        settings.oci_compartment_id = "test_compartment_id"

    def test_create_oci_provider(self):
        """
        Test the creation of an OCIProvider instance.
        """
        oci_provider = create_oci_provider(
            settings.oci_api_key,
            settings.oci_compartment_id,
            "test_model_name",
            temperature=0.3
        )
        self.assertIsInstance(oci_provider, OCIProvider)

    def test_generate(self):
        """
        Test the generate method of the OCIProvider class.
        """
        oci_provider = create_oci_provider(
            settings.oci_api_key,
            settings.oci_compartment_id,
            "test_model_name",
            temperature=0.3
        )
        response = oci_provider.generate("Test prompt")
        self.assertIsInstance(response, str)

if __name__ == "__main__":
    unittest.main()
```

This code follows the development guidelines and implements the requirements for the new OCI LLM provider. It includes proper error handling, logging, and documentation. The test file is placed in the correct location to mirror the source file's path under the `tests/` directory at the repository root.