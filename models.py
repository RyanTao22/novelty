from sqlalchemy import Column, Integer, String, DECIMAL, TIMESTAMP, Boolean, Enum, JSON, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from config import Base

class Player(Base):
    __tablename__ = 'players'
    __table_args__ = {
        'extend_existing': True,
        'mysql_engine': 'InnoDB',
        'mysql_charset': 'utf8mb4'
    }
    
    player_id = Column(String(30), primary_key=True)  # Format: a1 (a=round number, 1=participant number)
    total_earnings = Column(DECIMAL(10,2), default=0)
    current_round = Column(Integer, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())
    last_login = Column(TIMESTAMP, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    assets = relationship("UserAsset", back_populates="player", cascade="all, delete-orphan")
    stories = relationship("UserStory", back_populates="player", cascade="all, delete-orphan")

class Story(Base):
    __tablename__ = 'stories'
    __table_args__ = {'extend_existing': True}
    
    story_id = Column(String(30), primary_key=True)  # Format: a1_s1 (a=round number, 1=participant number, s=story number)
    player_id = Column(String(30), ForeignKey('players.player_id', ondelete='CASCADE'), nullable=False)
    round_id = Column(Integer, nullable=False)  # Round the story belongs to
    content = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    status = Column(Enum('draft', 'submitted', 'approved', 'rejected'), default='draft')
    score = Column(Integer)
    feedback = Column(Text)
    used_vocabularies = Column(JSON)  # Store list of used vocabulary IDs
    
    # No need to define relationships for views

class GameRound(Base):
    __tablename__ = 'game_rounds'
    __table_args__ = {'extend_existing': True}
    
    round_id = Column(Integer, primary_key=True, autoincrement=True)
    round_number = Column(Integer, nullable=False, unique=True)  # Actual round number
    start_time = Column(TIMESTAMP, server_default=func.now())
    end_time = Column(TIMESTAMP)
    status = Column(Enum('preparing', 'active', 'finished'), default='preparing')
    parameters = Column(JSON)  # Store vocabulary, combinations and story configurations for this round

class UserStory(Base):
    __tablename__ = 'user_stories'
    __table_args__ = {'extend_existing': True}
    
    story_id = Column(String(30), primary_key=True)  # Format: s1_a1 (s=story number, 1=round number, a=participant number)
    player_id = Column(String(30), ForeignKey('players.player_id', ondelete='CASCADE'), nullable=False)
    round_id = Column(Integer, nullable=False)  # Round the story belongs to
    content = Column(Text, nullable=False)  # Story content
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    used_vocabularies = Column(JSON)  # Store list of used vocabulary IDs
    
    # Relationships
    player = relationship("Player", back_populates="stories")

class UserAsset(Base):
    __tablename__ = 'user_assets'
    __table_args__ = {'extend_existing': True}
    
    asset_id = Column(String(30), primary_key=True)  # Format: a1_v1 (a=round number, 1=participant number, v=asset number)
    player_id = Column(String(30), ForeignKey('players.player_id', ondelete='CASCADE'), nullable=False)
    round_id = Column(Integer, nullable=False)  # Round the asset belongs to
    
    # Asset types: vocabulary, story_template, user_creation, story_draft
    asset_type = Column(Enum('vocabulary', 'story_template', 'user_creation', 'vocabulary_draw', 'story_draft'), nullable=False)
    
    content = Column(Text)  # Can be empty for vocabulary type
    created_at = Column(TIMESTAMP, server_default=func.now())
    status = Column(Enum('active', 'archived', 'submitted', 'approved', 'rejected'), default='active')
    score = Column(Integer)
    feedback = Column(Text)
    used_vocabularies = Column(JSON)  # Store list of used vocabulary IDs
    
    # Metadata - can store price, IP rate, and other additional information
    asset_metadata = Column(JSON)  # Renamed to avoid conflict with SQLAlchemy's internal metadata
    
    # Relationships
    player = relationship("Player", back_populates="assets")