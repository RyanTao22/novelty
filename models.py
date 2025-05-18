from sqlalchemy import Column, Integer, String, DECIMAL, TIMESTAMP, Boolean, Enum, JSON, Text, Float
from sqlalchemy.sql import func
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

class Story(Base):
    __tablename__ = 'stories'
    __table_args__ = {'extend_existing': True}
    
    story_id = Column(String(30), primary_key=True)  # Format: a1_s1 (a=round number, 1=participant number, s=story number)
    player_id = Column(String(30), nullable=False)
    round_id = Column(Integer, nullable=False)  # Round the story belongs to
    content = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    status = Column(Enum('draft', 'submitted', 'approved', 'rejected'), default='draft')
    score = Column(Integer)
    feedback = Column(Text)
    used_vocabularies = Column(JSON)  # Store list of used vocabulary IDs

class GameRound(Base):
    __tablename__ = 'game_rounds'
    __table_args__ = {'extend_existing': True}
    
    round_id = Column(Integer, primary_key=True, autoincrement=True)
    round_number = Column(Integer, nullable=False, unique=True)  # Actual round number
    start_time = Column(TIMESTAMP, server_default=func.now())
    end_time = Column(TIMESTAMP)
    status = Column(Enum('preparing', 'active', 'finished'), default='preparing')
    parameters = Column(JSON)  # Store vocabulary, combinations and story configurations for this round

class UserAsset(Base):
    __tablename__ = 'user_assets'
    __table_args__ = {'extend_existing': True}
    
    asset_id = Column(String(30), primary_key=True)  # Format: a1_v1 (a=round number, 1=participant number, v=asset number)
    player_id = Column(String(30), nullable=False)
    round_id = Column(Integer, nullable=False)  # Round the asset belongs to
    
    # Asset types: vocabulary, story_template, user_creation, story_draft
    asset_type = Column(Enum('vocabulary', 'story_template', 'user_creation', 'vocabulary_draw', 'story_draft'), nullable=False)
    
    content = Column(Text)  # Can be empty for vocabulary type
    created_at = Column(TIMESTAMP, server_default=func.now())
    status = Column(Enum('active', 'archived', 'submitted', 'approved', 'rejected'), default='active')
    score = Column(Integer)
    content_ip_rate = Column(Float)  # 内容IP费率，替换原来的feedback
    used_vocabularies = Column(JSON)  # Store list of used vocabulary IDs
    
    # Metadata - can store price, IP rate, and other additional information
    asset_metadata = Column(JSON)  # Renamed to avoid conflict with SQLAlchemy's internal metadata

class StoryRating(Base):
    __tablename__ = 'story_ratings'
    __table_args__ = {'extend_existing': True}
    
    rating_id = Column(String(30), primary_key=True)  # Format: r1_p1_s1 (r=rating, p=player id, s=story id)
    player_id = Column(String(30), nullable=False)
    asset_id = Column(String(30), nullable=False)
    
    # Rating items
    creativity_score = Column(Integer, nullable=False)  # Creativity rating (1-7)
    coherence_score = Column(Integer, nullable=False)  # Coherence rating (1-7)
    overall_score = Column(Integer, nullable=False)   # Overall rating (1-7)
    content_ip_rate = Column(Float, nullable=False)   # IP rate set by the rater
    original_ip_rate = Column(Float, nullable=True)   # Original IP rate set by the creator
    
    comment = Column(Text)  # Optional comment
    created_at = Column(TIMESTAMP, server_default=func.now())