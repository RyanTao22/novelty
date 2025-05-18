from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from models import Player, Story, GameRound, UserAsset, StoryRating
from cachetools import cached, TTLCache
import json
import logging
import random
from decimal import Decimal
import time
from sqlalchemy import func, and_

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache configuration
round_config_cache = TTLCache(maxsize=10, ttl=300)  # 5 minutes cache

class PlayerService:
    @staticmethod
    def get_player(db: Session, player_id: str) -> Optional[Player]:
        """Get player information"""
        return db.query(Player).filter(Player.player_id == player_id).first()

    @staticmethod
    def create_player(db: Session, player_id: str) -> Player:
        """Create a new player"""
        player = Player(
            player_id=player_id,
            total_earnings=100,  # Set initial balance to 100
            current_round=1,
            is_active=True
        )
        db.add(player)
        db.commit()
        return player

    @staticmethod
    def update_player_earnings(db: Session, player_id: str, amount: float):
        """Update player earnings"""
        player = db.query(Player).filter(Player.player_id == player_id).first()
        if player:
            player.total_earnings += amount
            db.commit()

    @staticmethod
    def update_player_balance(db: Session, player_id: str, new_balance: Decimal):
        """Set player balance directly"""
        player = db.query(Player).filter(Player.player_id == player_id).first()
        if player:
            player.total_earnings = new_balance
            db.commit()
            return True
        return False

class UserAssetService:
    @staticmethod
    def create_asset(db: Session, player_id: str, round_id: int, asset_type: str, content: str = None, 
                    vocab_ids: List[str] = None, metadata: Dict = None, content_ip_rate: float = None) -> UserAsset:
        """Create a new asset record"""
        # Generate asset ID: add millisecond timestamp and random number to ensure uniqueness
        timestamp = int(time.time() * 1000)  # Millisecond timestamp
        random_suffix = random.randint(1000, 9999)  # Random suffix
        type_prefix = asset_type[0].lower()  # Use the first letter of the type as prefix
        asset_id = f"{type_prefix}{round_id}_{player_id}_{timestamp}_{random_suffix}"
        
        asset = UserAsset(
            asset_id=asset_id,
            player_id=player_id,
            round_id=round_id,
            asset_type=asset_type,
            content=content,
            status='active',
            content_ip_rate=content_ip_rate,
            used_vocabularies=json.dumps(vocab_ids) if vocab_ids else None,
            asset_metadata=json.dumps(metadata) if metadata else None
        )
        db.add(asset)
        db.commit()
        return asset

    @staticmethod
    def get_player_assets(db: Session, player_id: str, asset_type: str = None) -> List[UserAsset]:
        """Get all assets of a player, optionally filter by type"""
        query = db.query(UserAsset).filter(UserAsset.player_id == player_id)
        if asset_type:
            query = query.filter(UserAsset.asset_type == asset_type)
        return query.order_by(UserAsset.created_at.desc()).all()
    
    @staticmethod
    def get_player_vocabularies(db: Session, player_id: str) -> set:
        """Get all vocabulary IDs owned by the player"""
        assets = UserAssetService.get_player_assets(db, player_id)
        vocab_ids = set()
        for asset in assets:
            if asset.used_vocabularies:
                try:
                    vocabs = json.loads(asset.used_vocabularies)
                    vocab_ids.update(vocabs)
                except:
                    pass
        return vocab_ids

    @staticmethod
    def get_asset_by_id(db: Session, asset_id: str) -> Optional[UserAsset]:
        """Get asset by ID"""
        return db.query(UserAsset).filter(UserAsset.asset_id == asset_id).first()

    @staticmethod
    def update_asset_status(db: Session, asset_id: str, status: str, score: Optional[int] = None, content_ip_rate: Optional[float] = None):
        """Update asset status"""
        asset = db.query(UserAsset).filter(UserAsset.asset_id == asset_id).first()
        if asset:
            asset.status = status
            if score is not None:
                asset.score = score
            if content_ip_rate is not None:
                asset.content_ip_rate = content_ip_rate
            db.commit()

    @staticmethod
    def update_asset(db: Session, asset_id: str, content: str) -> bool:
        """Update asset content"""
        asset = db.query(UserAsset).filter(UserAsset.asset_id == asset_id).first()
        if asset:
            asset.content = content
            # Update timestamp
            asset.updated_at = func.now()
            db.commit()
            return True
        return False

    @staticmethod
    def has_purchased_story(db: Session, player_id: str, story_content: str) -> bool:
        """Check if the player has purchased a specific story content"""
        return db.query(UserAsset).filter(
            UserAsset.player_id == player_id,
            UserAsset.content == story_content,
            UserAsset.asset_type == 'story_template'
        ).count() > 0

class GameRoundService:
    @staticmethod
    @cached(round_config_cache)
    def get_round_config(db: Session, round_number: int) -> Optional[Dict]:
        """Get round configuration (with cache)"""
        round_data = db.query(GameRound).filter(GameRound.round_number == round_number).first()
        if round_data:
            return round_data.parameters
        return None

    @staticmethod
    def get_vocabulary(db: Session, round_number: int, vocab_id: str) -> Optional[Dict]:
        """Get vocabulary information"""
        config = GameRoundService.get_round_config(db, round_number)
        if config:
            for vocab in config.get('vocabularies', []):
                if vocab['id'] == vocab_id:
                    return vocab
        return None

    @staticmethod
    def get_combination(db: Session, round_number: int, combination_id: str) -> Optional[Dict]:
        """Get combination information"""
        config = GameRoundService.get_round_config(db, round_number)
        if config:
            for combo in config.get('combinations', []):
                if combo['id'] == combination_id:
                    return combo
        return None

    @staticmethod
    def purchase_story_content(db: Session, player_id: str, round_number: int, combination_id: str, story_index: int = 0) -> bool:
        """Purchase story content"""
        print(f"SERVER DEBUG - purchase_story_content: player={player_id}, round={round_number}, combo={combination_id}, story_index={story_index}")
        
        combo = GameRoundService.get_combination(db, round_number, combination_id)
        if not combo or story_index >= len(combo['stories']):
            print(f"SERVER DEBUG - Invalid combination or story index: {combination_id}, {story_index}")
            return False

        # Get vocabularies owned by the player
        owned_vocabs = UserAssetService.get_player_vocabularies(db, player_id)
        print(f"SERVER DEBUG - owned_vocabs: {owned_vocabs}")

        # Calculate total vocabulary price and price of already owned vocabularies
        config = GameRoundService.get_round_config(db, round_number)
        total_vocab_price = Decimal('0')
        owned_vocab_price = Decimal('0')
        for vocab_id in combo['vocab_ids']:
            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
            if vocab:
                total_vocab_price += Decimal(str(vocab['price']))
                print(f"SERVER DEBUG - vocab: {vocab['word']} ${vocab['price']}")
                if vocab_id in owned_vocabs:
                    owned_vocab_price += Decimal(str(vocab['price']))
                    print(f"SERVER DEBUG - already owned: {vocab['word']} ${vocab['price']}")
        
        print(f"SERVER DEBUG - total_vocab_price: ${total_vocab_price}, owned_vocab_price: ${owned_vocab_price}")

        # Get the correct story data by story_index
        if story_index >= len(combo['stories']):
            print(f"SERVER WARNING - Story index {story_index} out of range, fallback to first story")
            story = combo['stories'][0]
            story_index = 0
        else:
            story = combo['stories'][story_index]
        
        print(f"SERVER DEBUG - Selected story: id={story['id']}, index={story_index}, rating={story.get('rating', 'N/A')}, content={story['content'][:50]}...")
        
        # Calculate content price - extra part of the story
        content_price = total_vocab_price * (Decimal(str(story['content_ip_rate'])) - Decimal('1'))
        print(f"SERVER DEBUG - content_ip_rate: {story['content_ip_rate']}, content_price: ${content_price}")
        
        # Calculate the actual amount to be paid: content extra price + price of missing vocabularies
        # Price of missing vocabularies = total vocabulary price - price of already owned vocabularies
        missing_vocab_price = total_vocab_price - owned_vocab_price
        
        # Actual price = content extra price + price of missing vocabularies
        actual_price = content_price + missing_vocab_price
        
        # If the user already owns all vocabularies, only charge content price
        if missing_vocab_price == 0:
            actual_price = content_price
            print(f"SERVER DEBUG - All vocabularies already owned, charging content price only: ${content_price}")
        
        print(f"SERVER DEBUG - missing_vocab_price: ${missing_vocab_price}, actual_price: ${actual_price}")

        # Check if the story has already been purchased
        if UserAssetService.has_purchased_story(db, player_id, story['content']):
            print(f"SERVER DEBUG - Player already purchased this story")
            return False

        # Check player balance
        player = PlayerService.get_player(db, player_id)
        if not player or player.total_earnings < actual_price:
            print(f"SERVER DEBUG - Insufficient balance: ${player.total_earnings if player else 0} < ${actual_price}")
            return False

        # Deduct cost
        PlayerService.update_player_earnings(db, player_id, -actual_price)
        print(f"SERVER DEBUG - Deducted ${actual_price} from player {player_id}")

        # Create story asset record
        metadata = {
            'story_id': story['id'],
            'price_paid': float(actual_price),
            'content_price': float(content_price),
            'rating': story.get('rating')
        }
        
        UserAssetService.create_asset(
            db=db,
            player_id=player_id,
            round_id=round_number,
            asset_type='story_template',
            content=story['content'],
            vocab_ids=combo['vocab_ids'],
            metadata=metadata
        )
        print(f"SERVER DEBUG - Created story asset with content from story_index {story_index}")

        return True

    @staticmethod
    def purchase_combination(db: Session, player_id: str, round_number: int, combination_id: str) -> bool:
        """Purchase vocabulary combination"""
        combo = GameRoundService.get_combination(db, round_number, combination_id)
        if not combo:
            return False

        # Calculate total vocabulary price
        config = GameRoundService.get_round_config(db, round_number)
        total_vocab_price = Decimal('0')
        for vocab_id in combo['vocab_ids']:
            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
            if vocab:
                total_vocab_price += Decimal(str(vocab['price']))

        # Check player balance
        player = PlayerService.get_player(db, player_id)
        if not player or player.total_earnings < total_vocab_price:
            return False

        # Deduct cost
        PlayerService.update_player_earnings(db, player_id, -total_vocab_price)

        # Create vocabulary asset record
        metadata = {
            'combo_id': combo['id'],
            'price_paid': float(total_vocab_price)
        }
        
        UserAssetService.create_asset(
            db=db,
            player_id=player_id,
            round_id=round_number,
            asset_type='vocabulary',
            content="",  # Empty content
            vocab_ids=combo['vocab_ids'],
            metadata=metadata
        )

        return True

    @staticmethod
    def transfer_story_content(db: Session, from_player_id: str, to_player_id: str, story_id: str) -> bool:
        """Transfer story content"""
        story = db.query(UserAsset).filter(
            UserAsset.asset_id == story_id,
            UserAsset.player_id == from_player_id,
            UserAsset.asset_type == 'story_template'
        ).first()
        
        if not story:
            return False

        # Get combination information
        try:
            used_vocabs = json.loads(story.used_vocabularies) if story.used_vocabularies else []
            metadata = json.loads(story.asset_metadata) if story.asset_metadata else {}
            
            # Get round configuration
            config = GameRoundService.get_round_config(db, story.round_id)
            if not config:
                return False
                
            # Calculate total vocabulary price
            total_vocab_price = Decimal('0')
            for vocab_id in used_vocabs:
                vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                if vocab:
                    total_vocab_price += Decimal(str(vocab['price']))
            
            # Get content IP rate
            content_ip_rate = Decimal(str(metadata.get('content_ip_rate', 1.5)))
            
            # Calculate transfer price - only content extra price
            transfer_price = total_vocab_price * (content_ip_rate - Decimal('1'))
            
            # Check receiver balance
            to_player = PlayerService.get_player(db, to_player_id)
            if not to_player or to_player.total_earnings < transfer_price:
                return False
                
            # Execute transfer
            PlayerService.update_player_earnings(db, to_player_id, -transfer_price)
            PlayerService.update_player_earnings(db, from_player_id, transfer_price)
            
            # Create new story asset
            metadata['price_paid'] = float(transfer_price)
            metadata['transfered_from'] = from_player_id
            
            UserAssetService.create_asset(
                db=db,
                player_id=to_player_id,
                round_id=story.round_id,
                asset_type='story_template',
                content=story.content,
                vocab_ids=used_vocabs,
                metadata=metadata
            )
            
            return True
        except Exception as e:
            print(f"ERROR - transfer_story_content: {str(e)}")
            return False

    @staticmethod
    def draw_random_vocabulary(db: Session, player_id: str, round_number: int) -> Dict:
        """Draw a random vocabulary"""
        # Get configuration
        config = GameRoundService.get_round_config(db, round_number)
        if not config:
            return {"success": False, "message": "Cannot get round configuration"}
            
        # Check player balance
        player = PlayerService.get_player(db, player_id)
        if not player:
            return {"success": False, "message": "Player does not exist"}
            
        # Check balance is sufficient
        draw_price = Decimal('10.0')  # Fixed draw price at 10 yuan
        if player.total_earnings < draw_price:
            return {"success": False, "message": "Insufficient balance"}
            
        # Get player's purchased vocabularies
        owned_vocabs = UserAssetService.get_player_vocabularies(db, player_id)
        
        # Filter out unpurchased vocabularies
        available_vocabs = []
        for vocab in config.get('vocabularies', []):
            if vocab['id'] not in owned_vocabs:
                available_vocabs.append(vocab)
                
        # Check if there are any vocabularies to draw
        if not available_vocabs:
            return {"success": False, "message": "Already owns all vocabularies"}
            
        # Draw a random vocabulary
        selected_vocab = random.choice(available_vocabs)
        
        # Deduct cost
        PlayerService.update_player_earnings(db, player_id, -draw_price)
        
        # Create draw vocabulary record
        metadata = {
            'price_paid': float(draw_price),
            'draw_method': 'random'
        }
        
        UserAssetService.create_asset(
            db=db,
            player_id=player_id,
            round_id=round_number,
            asset_type='vocabulary_draw',
            content=f"Drawn vocabulary: {selected_vocab['word']}",
            vocab_ids=[selected_vocab['id']],
            metadata=metadata
        )
        
        return {
            "success": True, 
            "vocab": selected_vocab,
            "price_paid": float(draw_price)
        }

class StoryRatingService:
    @staticmethod
    def create_rating(db: Session, player_id: str, asset_id: str, 
                     creativity_score: int, coherence_score: int, overall_score: int,
                     content_ip_rate: float, comment: str = None, original_ip_rate: float = None) -> Optional[StoryRating]:
        """Create a new story rating"""
        # 检查评分范围
        if not (1 <= creativity_score <= 7 and 1 <= coherence_score <= 7 and 1 <= overall_score <= 7):
            return None
            
        # 检查IP费率范围
        if not (1.0 <= content_ip_rate <= 3.0):
            content_ip_rate = 1.5  # If out of range, set to default value 1.5
            
        # 检查用户是否已对该故事评分
        existing_rating = db.query(StoryRating).filter(
            StoryRating.player_id == player_id,
            StoryRating.asset_id == asset_id
        ).first()
        
        if existing_rating:
            # 如果用户已经评分，返回None而不是更新评分
            return None
        
        # 创建新评分
        timestamp = int(time.time() * 1000)
        random_suffix = random.randint(1000, 9999)
        rating_id = f"r{timestamp}_{player_id}_{random_suffix}"
        
        rating = StoryRating(
            rating_id=rating_id,
            player_id=player_id,
            asset_id=asset_id,
            creativity_score=creativity_score,
            coherence_score=coherence_score,
            overall_score=overall_score,
            content_ip_rate=content_ip_rate,
            original_ip_rate=original_ip_rate,
            comment=comment
        )
        
        db.add(rating)
        db.commit()
        return rating
    
    @staticmethod
    def get_story_ratings(db: Session, asset_id: str) -> List[StoryRating]:
        """Get all ratings for a story"""
        return db.query(StoryRating).filter(StoryRating.asset_id == asset_id).all()
    
    @staticmethod
    def get_player_ratings(db: Session, player_id: str) -> List[StoryRating]:
        """Get all ratings by a player"""
        return db.query(StoryRating).filter(StoryRating.player_id == player_id).all()
    
    @staticmethod
    def get_rating(db: Session, player_id: str, asset_id: str) -> Optional[StoryRating]:
        """Get a specific player's rating for a specific story"""
        return db.query(StoryRating).filter(
            StoryRating.player_id == player_id,
            StoryRating.asset_id == asset_id
        ).first()
    
    @staticmethod
    def calculate_story_average_ratings(db: Session, asset_id: str) -> Dict:
        """Calculate average ratings for a story"""
        ratings = StoryRatingService.get_story_ratings(db, asset_id)
        
        if not ratings:
            return {
                "creativity_avg": 0,
                "coherence_avg": 0,
                "overall_avg": 0,
                "content_ip_rate_avg": 1.5,
                "rating_count": 0
            }
        
        creativity_sum = sum(rating.creativity_score for rating in ratings)
        coherence_sum = sum(rating.coherence_score for rating in ratings)
        overall_sum = sum(rating.overall_score for rating in ratings)
        ip_rate_sum = sum(rating.content_ip_rate for rating in ratings)
        count = len(ratings)
        
        return {
            "creativity_avg": round(creativity_sum / count, 2),
            "coherence_avg": round(coherence_sum / count, 2),
            "overall_avg": round(overall_sum / count, 2),
            "content_ip_rate_avg": round(ip_rate_sum / count, 2),
            "rating_count": count
        }
        
    @staticmethod
    def get_submitted_stories_for_rating(db: Session, round_id: int) -> List[UserAsset]:
        """Get submitted stories from the previous round for rating"""
        # 获取上一轮的故事
        previous_round = round_id
        if previous_round < 1:
            previous_round = 1  # Default to at least round 1
            
        # 查询上一轮的所有已提交故事
        stories = db.query(UserAsset).filter(
            UserAsset.round_id == previous_round,
            UserAsset.asset_type == 'user_creation',
            UserAsset.status == 'submitted'
        ).order_by(UserAsset.created_at.desc()).all()
        
        return stories
        
    @staticmethod
    def generate_next_round_story_data(db: Session, round_id: int) -> List[Dict]:
        """Generate story data for the next round based on ratings, keeping format consistent with game_rounds"""
        # 获取当前轮次的所有已提交故事
        stories = db.query(UserAsset).filter(
            UserAsset.round_id == round_id,
            UserAsset.asset_type == 'user_creation',
            UserAsset.status == 'submitted'
        ).all()
        
        next_round_stories = []
        
        # 为每个故事生成下一轮游戏所需的结构
        for story in stories:
            # 获取故事的平均评分
            avg_ratings = StoryRatingService.calculate_story_average_ratings(db, story.asset_id)
            
            # 获取故事使用的词汇
            vocab_ids = []
            if story.used_vocabularies:
                try:
                    vocab_ids = json.loads(story.used_vocabularies)
                except:
                    pass
            
            # 构建与game_rounds中兼容的故事数据
            story_data = {
                "id": story.asset_id,
                "content": story.content,
                "rating": avg_ratings["overall_avg"] or 4.0,  # Use overall rating as the rating
                "content_ip_rate": avg_ratings["content_ip_rate_avg"] or 1.5,  # Use average IP rate
                "vocab_ids": vocab_ids,
                "creator": story.player_id
            }
            
            next_round_stories.append(story_data)
        
        return next_round_stories

class StoryValidationService:
    @staticmethod
    def validate_story(story_content: str, owned_vocab_words: List[str]) -> Dict:
        """
        Validate if a story meets the specified rules:
        1. Each sentence must contain exactly one word or phrase
        2. Each word or phrase can only be used in one sentence
        3. All words or phrases must be used, and the number of sentences = number of words/phrases
        
        Args:
            story_content: Story content
            owned_vocab_words: List of owned words or phrases
            
        Returns:
            Dict containing validation result and message
            {
                "valid": True/False,
                "message": "Success/Error message",
                "matches": {} # Mapping of sentence indices to matched words (only when valid=True)
            }
        """
        import re
        
        # 1. Split into sentences
        sentences = [s.strip() for s in re.split(r'[.!?]+', story_content) if s.strip()]
        
        # 2. Check if each sentence contains exactly one word or phrase
        sentence_word_matches = {}
        used_words = set()
        
        for i, sentence in enumerate(sentences):
            sentence_matches = []
            
            for word in owned_vocab_words:
                if word.lower() in sentence.lower():
                    sentence_matches.append(word)
                    
            # Check number of vocabulary matches in the current sentence
            if len(sentence_matches) == 0:
                return {
                    "valid": False,
                    "message": f"Sentence {i+1} does not contain any purchased words or phrases."
                }
            elif len(sentence_matches) > 1:
                return {
                    "valid": False,
                    "message": f"Sentence {i+1} contains multiple words or phrases: {', '.join(sentence_matches)}. Each sentence should contain only one word or phrase."
                }
            
            # Check if the word has already been used in other sentences
            word = sentence_matches[0]
            if word in used_words:
                return {
                    "valid": False,
                    "message": f"Word or phrase '{word}' is used in multiple sentences. Each word or phrase should be used in only one sentence."
                }
            
            # Add to used words and sentence matches dictionary
            used_words.add(word)
            sentence_word_matches[i] = word
        
        # 3. Check if all vocabulary is used (number of sentences = number of vocabulary)
        if len(sentences) != len(owned_vocab_words):
            if len(sentences) < len(owned_vocab_words):
                return {
                    "valid": False,
                    "message": f"You own {len(owned_vocab_words)} words or phrases, but there are only {len(sentences)} sentences. Each word or phrase must be used in a sentence."
                }
            else:
                return {
                    "valid": False,
                    "message": f"You own {len(owned_vocab_words)} words or phrases, but there are {len(sentences)} sentences. Each sentence must use exactly one word or phrase."
                }
        
        # 4. Check if all vocabulary is used
        unused_words = set(owned_vocab_words) - used_words
        if unused_words:
            return {
                "valid": False,
                "message": f"The following words or phrases are not used: {', '.join(unused_words)}. All words or phrases must be used."
            }
            
        # All checks passed
        return {
            "valid": True,
            "message": "Story check passed! Each sentence uses one word or phrase, and all words or phrases are used.",
            "matches": sentence_word_matches
        }