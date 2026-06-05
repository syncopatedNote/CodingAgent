import os

class Settings:
    def __init__(self):
        self.DB_HOST = os.getenv('DB_HOST', 'localhost')
        self.DB_PORT = os.getenv('DB_PORT', '5432')
        self.DB_NAME = os.getenv('DB_NAME', 'chat_db')
        self.DB_USER = os.getenv('DB_USER', 'user')
        self.DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
        self.STREAMLIT_PORT = os.getenv('STREAMLIT_PORT', '8501')
        self.MCP_SERVER_PORT = os.getenv('MCP_SERVER_PORT', '8000')
        self.CHAT_SERVICE_URL = os.getenv('CHAT_SERVICE_URL', 'http://localhost:8000')

settings = Settings()