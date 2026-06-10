import logging
from typing import List
from langchain.llms import BaseLLM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OCILLMProvider(BaseLLM):
    """
    A provider for interacting with Oracle Cloud Infrastructure's LLM service.
    
    Attributes:
        api_key (str): The API key for authentication.
        region (str): The region where the OCI service is hosted.
    """    
    
    def __init__(self, api_key: str, region: str):
        if not api_key or not region:
            raise ValueError("API key and region must be provided")
        self.api_key = api_key
        self.region = region
        logger.info("OCILLMProvider initialized")
    
    def generate(self, prompt: str, max_tokens: int = 150) -> str:
        """
        Generate text based on the given prompt.
        
        Args:
            prompt (str): The input prompt.
            max_tokens (int): The maximum number of tokens to generate.
        
        Returns:
            str: The generated text.
        
        Raises:
            ValueError: If max_tokens is not a positive integer.
        """   
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        
        try:
            response = self._call_oci_api(prompt, max_tokens)
            return response
        except Exception as e:
            logger.error(f"Error generating text: {e}")
            raise
    
    def _call_oci_api(self, prompt: str, max_tokens: int) -> str:
        """
        Placeholder for the actual API call to Oracle Cloud Infrastructure.
        
        Args:
            prompt (str): The input prompt.
            max_tokens (int): The maximum number of tokens to generate.
        
        Returns:
            str: The generated text.
        """
        logger.info("Calling OCI API")
        # Replace with actual API call to OCI
        return f"Generated text for prompt: {prompt}"
    
    def list_models(self) -> List[str]:
        """
        List available models in the OCI service.
        
        Returns:
            List[str]: A list of model names.
        """
        try:
            models = self._list_oci_models()
            return models
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            raise
    
    def _list_oci_models(self) -> List[str]:
        """
        Placeholder for the actual API call to list models in OCI.
        
        Returns:
            List[str]: A list of model names.
        """
        logger.info("Listing OCI models")
        # Replace with actual API call to list models in OCI
        return ["model1", "model2"]


from typing import List
from.oci import OCILLMProvider
from.other_provider import OtherLLMProvider

class LLMManager:
    """
    A manager for handling different LLM providers.
    
    Attributes:
        provider (str): The name of the LLM provider.
        api_key (str): The API key for authentication.
        region (str): The region where the service is hosted (if applicable).
        llm_provider: The instantiated LLM provider.
    """    
    
    def __init__(self, provider: str, api_key: str, region: str = None):
        if not api_key:
            raise ValueError("API key must be provided")
        self.provider = provider
        self.api_key = api_key
        self.region = region
        self._initialize_provider()
    
    def _initialize_provider(self):
        """
        Initialize the appropriate LLM provider based on the provider name.
        """
        if self.provider == "oci":
            if not self.region:
                raise ValueError("Region must be provided for OCI provider")
            self.llm_provider = OCILLMProvider(self.api_key, self.region)
        elif self.provider == "other":
            self.llm_provider = OtherLLMProvider(self.api_key)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def generate(self, prompt: str, max_tokens: int = 150) -> str:
        """
        Generate text based on the given prompt using the selected LLM provider.
        
        Args:
            prompt (str): The input prompt.
            max_tokens (int): The maximum number of tokens to generate.
        
        Returns:
            str: The generated text.
        """
        return self.llm_provider.generate(prompt, max_tokens)
    
    def list_models(self) -> List[str]:
        """
        List available models using the selected LLM provider.
        
        Returns:
            List[str]: A list of model names.
        """
        return self.llm_provider.list_models()


import logging
import os
from llm_base import LLMManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """
    Example usage of the LLMManager.
    """
    api_key = os.getenv("OCI_API_KEY")
    region = os.getenv("OCI_REGION")    
    if not api_key or not region:
        logger.error("API key or region not provided")
        return    
    try:
        llm = LLMManager(provider="oci", api_key=api_key, region=region)
        response = llm.generate("Hello, world!", max_tokens=50)
        print(response)
        models = llm.list_models()
        print(models)
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()