from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env",extra="ignore")
    '''agent相关配置'''
    AGENT_NAME: str = 'agent'
    VERSION: str = '1.0.0'

    '''大模型相关配置'''
    LLM_BASE_URL: str ='https://api.openai.com/v1'
    LLM_API_KEY: str ='sk-xxx'
    LLM_MODEL: str ='gpt-4o-mini'
    LLM_TIMEOUT: int =60
    LLM_MAX_RETRIES: int =3



@lru_cache()
def get_settings() -> Settings:
    return Settings()
