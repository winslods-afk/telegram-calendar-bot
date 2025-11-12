"""
Модуль для работы с базой данных PostgreSQL
"""

import os
import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

Base = declarative_base()


class User(Base):
    """Модель пользователя в БД"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True, nullable=False, index=True)
    icloud_username = Column(String, nullable=True)
    icloud_password = Column(String, nullable=True)
    icloud_url = Column(String, default='https://caldav.icloud.com/')
    check_interval_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<User(chat_id={self.chat_id}, username={self.icloud_username})>"


class SentEvent(Base):
    """Модель для отслеживания отправленных событий"""
    __tablename__ = 'sent_events'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    event_uid = Column(String, nullable=False, index=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<SentEvent(user_id={self.user_id}, event_uid={self.event_uid})>"


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self):
        # Получаем параметры подключения из переменных окружения
        # Поддерживаем DATABASE_URL (стандарт для многих платформ) или отдельные переменные
        database_url = os.getenv('DATABASE_URL')
        
        if not database_url:
            # Если DATABASE_URL не указан, собираем из отдельных переменных
            db_host = os.getenv('DB_HOST', 'localhost')
            db_port = os.getenv('DB_PORT', '5432')
            db_name = os.getenv('DB_NAME', 'calendar_bot')
            db_user = os.getenv('DB_USER', 'postgres')
            db_password = os.getenv('DB_PASSWORD', 'postgres')
            
            # Если пароль содержит специальные символы, нужно их экранировать
            from urllib.parse import quote_plus
            db_password_encoded = quote_plus(db_password)
            
            database_url = f"postgresql://{db_user}:{db_password_encoded}@{db_host}:{db_port}/{db_name}"
        
        # Если DATABASE_URL начинается с postgres://, меняем на postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        logger.info(f"Подключение к БД: {database_url.split('@')[1] if '@' in database_url else 'скрыто'}")
        
        self.engine = create_engine(
            database_url, 
            echo=False,
            pool_pre_ping=True,  # Проверяет соединение перед использованием
            pool_recycle=3600    # Переподключается каждый час
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Создаем таблицы (с повторными попытками)
        self.create_tables()
    
    def create_tables(self):
        """Создает таблицы в БД"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                Base.metadata.create_all(bind=self.engine)
                logger.info("Таблицы БД созданы/проверены")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Попытка {attempt + 1}/{max_retries} подключения к БД не удалась: {e}")
                    import time
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Ошибка при создании таблиц после {max_retries} попыток: {e}")
                    logger.error("Проверьте настройки подключения к БД в переменных окружения:")
                    logger.error("- DATABASE_URL (полный URL) или")
                    logger.error("- DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD")
                    raise
    
    def get_session(self) -> Session:
        """Возвращает сессию БД"""
        return self.SessionLocal()
    
    def get_user(self, chat_id: int) -> Optional[User]:
        """Получает пользователя по chat_id"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            return user
        except Exception as e:
            logger.error(f"Ошибка при получении пользователя: {e}")
            return None
        finally:
            session.close()
    
    def create_user(self, chat_id: int) -> User:
        """Создает нового пользователя"""
        session = self.get_session()
        try:
            user = User(chat_id=chat_id)
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info(f"Создан новый пользователь: chat_id={chat_id}")
            return user
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при создании пользователя: {e}")
            raise
        finally:
            session.close()
    
    def update_user_credentials(self, chat_id: int, icloud_username: str, 
                                icloud_password: str, icloud_url: str = None) -> bool:
        """Обновляет учетные данные пользователя"""
        session = self.get_session()
        try:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                user = self.create_user(chat_id)
            
            user.icloud_username = icloud_username
            user.icloud_password = icloud_password
            if icloud_url:
                user.icloud_url = icloud_url
            user.updated_at = datetime.utcnow()
            
            session.commit()
            logger.info(f"Обновлены учетные данные для пользователя: chat_id={chat_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении учетных данных: {e}")
            return False
        finally:
            session.close()
    
    def get_active_users(self) -> List[User]:
        """Получает список активных пользователей"""
        session = self.get_session()
        try:
            users = session.query(User).filter(
                User.is_active == True,
                User.icloud_username.isnot(None),
                User.icloud_password.isnot(None)
            ).all()
            return users
        except Exception as e:
            logger.error(f"Ошибка при получении активных пользователей: {e}")
            return []
        finally:
            session.close()
    
    def is_event_sent(self, user_id: int, event_uid: str) -> bool:
        """Проверяет, было ли событие уже отправлено"""
        session = self.get_session()
        try:
            sent_event = session.query(SentEvent).filter(
                SentEvent.user_id == user_id,
                SentEvent.event_uid == event_uid
            ).first()
            return sent_event is not None
        except Exception as e:
            logger.error(f"Ошибка при проверке отправленного события: {e}")
            return False
        finally:
            session.close()
    
    def mark_event_as_sent(self, user_id: int, event_uid: str):
        """Отмечает событие как отправленное"""
        session = self.get_session()
        try:
            # Проверяем, не было ли уже отправлено
            if not self.is_event_sent(user_id, event_uid):
                sent_event = SentEvent(user_id=user_id, event_uid=event_uid)
                session.add(sent_event)
                session.commit()
                logger.debug(f"Событие {event_uid} отмечено как отправленное для пользователя {user_id}")
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при отметке события как отправленного: {e}")
        finally:
            session.close()

