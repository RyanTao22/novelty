import streamlit as st
from typing import List, Dict
from models import Player, UserAsset, GameRound
from service import PlayerService, UserAssetService, GameRoundService, StoryValidationService
from config import get_db
import json
import logging
from decimal import Decimal
import re
from datetime import datetime, timedelta
import time
import difflib  # 添加difflib库导入

# 移除缓存装饰器，直接调用数据库的函数
def get_round_config(round_id):
    """获取回合配置信息"""
    db = next(get_db())
    try:
        return GameRoundService.get_round_config(db, round_id)
    finally:
        db.close()

def get_player_assets(player_id):
    """获取玩家资产信息"""
    db = next(get_db())
    try:
        return UserAssetService.get_player_assets(db, player_id)
    finally:
        db.close()

def get_player_vocabularies(player_id):
    """获取玩家词汇信息"""
    db = next(get_db())
    try:
        return UserAssetService.get_player_vocabularies(db, player_id)
    finally:
        db.close()

def get_player_info(player_id):
    """获取玩家信息"""
    db = next(get_db())
    try:
        player = PlayerService.get_player(db, player_id)
        if not player:
            player = PlayerService.create_player(db, player_id)
        return player
    finally:
        db.close()

# Set page configuration
st.set_page_config(layout="wide", page_title="Science Fiction Creation", page_icon="📚")

# Initialize session state
def init_session_state():
    # Check if logged in
    if 'player_id' not in st.session_state or st.session_state.player_id == "":
        st.switch_page("pages/1_Instructions_Page.py")
        return
    
    # If already initialized, no need to execute again
    # But need to ensure story_content and temp_story_content stay in sync
    if 'initialized' in st.session_state:
        # Preserve current story content to prevent loss after page refresh
        if 'story_content' in st.session_state and 'temp_story_content' not in st.session_state:
            st.session_state.temp_story_content = st.session_state.story_content
        elif 'temp_story_content' in st.session_state and 'story_content' not in st.session_state:
            st.session_state.story_content = st.session_state.temp_story_content
        return
        
    # 获取数据，不使用缓存
    st.session_state.round_config = get_round_config(st.secrets['round_id'])
    
    # 获取玩家信息并立即获取total_earnings值，避免DetachedInstanceError
    db = next(get_db())
    try:
        player = PlayerService.get_player(db, st.session_state.player_id)
        if not player:
            player = PlayerService.create_player(db, st.session_state.player_id)
        
        # 直接获取并存储属性值，而不是存储整个对象
        st.session_state.player_info = player
        st.session_state.initial_balance = Decimal(str(st.session_state.round_config['initial_balance']))
        st.session_state.current_balance = Decimal(str(player.total_earnings))  # 直接获取值
    finally:
        db.close()
    
    # Get all vocabularies owned by the player
    st.session_state.owned_vocabs = get_player_vocabularies(st.session_state.player_id)
    
    # Load player's existing assets
    st.session_state.player_assets = get_player_assets(st.session_state.player_id)
    
    # Initialize transaction history and story content
    st.session_state.transaction_history = []
    st.session_state.initialized = True
    
    # Initialize story content - try to load latest content from saved drafts
    st.session_state.story_content = ""
    story_drafts = [asset for asset in st.session_state.player_assets
                    if asset.asset_type == 'story_draft' and asset.content]
    if story_drafts:
        # Sort by creation time to find the latest draft
        latest_draft = sorted(story_drafts, key=lambda x: x.created_at, reverse=True)[0]
        st.session_state.story_content = latest_draft.content
        # Also initialize temporary content
        st.session_state.temp_story_content = latest_draft.content

# Local transaction handling functions
def handle_purchase_combination(combo_id: str):
    combo = next((c for c in st.session_state.round_config['combinations'] if c['id'] == combo_id), None)
    if not combo:
        return False, "Combination not found"
    
    # Check if all vocabularies are already owned
    if all(vocab_id in st.session_state.owned_vocabs for vocab_id in combo['vocab_ids']):
        return False, "You already own all words in this combination"
    
    # 保存原始状态以便回滚
    original_balance = st.session_state.current_balance
    original_owned_vocabs = set(st.session_state.owned_vocabs)
    
    try:
        # Calculate total price
        total_cost = Decimal('0')
        for vocab_id in combo['vocab_ids']:
            vocab = next((v for v in st.session_state.round_config['vocabularies'] if v['id'] == vocab_id), None)
            if vocab:
                total_cost += Decimal(str(vocab['price']))
        
        # Check if balance is sufficient
        if total_cost > st.session_state.current_balance:
            return False, "Insufficient balance"
        
        # Update local state
        st.session_state.owned_vocabs.update(combo['vocab_ids'])
        st.session_state.current_balance -= total_cost
        
        # Create asset record
        metadata = {
            'combo_id': combo['id'],
            'price_paid': float(total_cost)
        }
        
        new_asset = UserAsset(
            player_id=st.session_state.player_id,
            round_id=st.secrets['round_id'],
            asset_type='vocabulary',
            content="",  # Empty content
            used_vocabularies=json.dumps(combo['vocab_ids']),
            asset_metadata=json.dumps(metadata)
        )
        st.session_state.player_assets.append(new_asset)
        
        # Record transaction
        st.session_state.transaction_history.append({
            'type': 'purchase_combination',
            'combo_id': combo_id,
            'cost': total_cost
        })
        
        return True, "Purchase successful"
    except Exception as e:
        # 发生异常时回滚状态
        st.session_state.current_balance = original_balance
        st.session_state.owned_vocabs = original_owned_vocabs
        return False, f"Transaction failed: {str(e)}"

def handle_purchase_story_content(combo_id: str, story_index: int):
    print(f"DEBUG - Purchase story content started: combo_id={combo_id}, story_index={story_index}")
    
    # 保存原始状态以便回滚
    original_balance = st.session_state.current_balance
    original_owned_vocabs = set(st.session_state.owned_vocabs)
    original_assets = list(st.session_state.player_assets)
    
    try:
        combo = next((c for c in st.session_state.round_config['combinations'] if c['id'] == combo_id), None)
        if not combo or story_index >= len(combo['stories']):
            print(f"DEBUG - Invalid combo or story index: combo_id={combo_id}, story_index={story_index}")
            return False, "Invalid story selection"
        
        story = combo['stories'][story_index]
        
        # Check if this specific story is already owned
        already_owns_story = any(
            asset.content == story['content'] and asset.asset_type == 'story_template'
            for asset in st.session_state.player_assets 
            if asset.content
        )
        
        if already_owns_story:
            return False, "You have already purchased this story"
        
        # Calculate price
        total_vocab_price = Decimal('0')
        missing_vocab_price = Decimal('0')
        
        # Calculate vocabulary prices
        for vocab_id in combo['vocab_ids']:
            vocab = next((v for v in st.session_state.round_config['vocabularies'] if v['id'] == vocab_id), None)
            if vocab:
                total_vocab_price += Decimal(str(vocab['price']))
                if vocab_id not in st.session_state.owned_vocabs:
                    missing_vocab_price += Decimal(str(vocab['price']))
        
        # Calculate content additional price
        content_price = total_vocab_price * (Decimal(str(story['content_ip_rate'])) - Decimal('1'))
        
        # Final price = content additional price + missing vocabulary price
        final_price = content_price + missing_vocab_price
        
        # Actual payment price - if no missing vocabularies, only pay content price
        actual_price = content_price if missing_vocab_price == 0 else final_price
        
        # Check if balance is sufficient
        if actual_price > st.session_state.current_balance:
            return False, "Insufficient balance"
        
        # Update local state
        st.session_state.owned_vocabs.update(combo['vocab_ids'])
        st.session_state.current_balance -= actual_price
        
        # Add story to local - create asset object
        metadata = {
            'story_id': story['id'],
            'price_paid': float(actual_price),
            'content_price': float(content_price),
            'content_ip_rate': float(story['content_ip_rate']),
            'rating': story.get('rating')
        }
        
        new_asset = UserAsset(
            player_id=st.session_state.player_id,
            round_id=st.secrets['round_id'],
            asset_type='story_template',
            content=story['content'],
            used_vocabularies=json.dumps(combo['vocab_ids']),
            asset_metadata=json.dumps(metadata)
        )
        st.session_state.player_assets.append(new_asset)
        
        # Record transaction
        st.session_state.transaction_history.append({
            'type': 'purchase_story',
            'combo_id': combo_id,
            'story_index': story_index,
            'cost': actual_price,
            'content_price': content_price,
            'missing_vocab_price': missing_vocab_price,
            'total_vocab_price': total_vocab_price,
            'story_id': story['id']
        })
        
        return True, f"Purchase successful! New balance: ${st.session_state.current_balance:.2f}"
    except Exception as e:
        # 发生异常时回滚状态
        st.session_state.current_balance = original_balance
        st.session_state.owned_vocabs = original_owned_vocabs
        st.session_state.player_assets = original_assets
        return False, f"Transaction failed: {str(e)}"

def handle_draw_random_word():
    # 保存原始状态以便回滚
    original_balance = st.session_state.current_balance
    original_owned_vocabs = set(st.session_state.owned_vocabs)
    original_assets = list(st.session_state.player_assets)
    
    try:
        # Get available vocabularies
        available_vocabs = [
            v for v in st.session_state.round_config['vocabularies']
            if v['id'] not in st.session_state.owned_vocabs
        ]
        
        if not available_vocabs:
            return False, "No more words available to draw"
        
        # Randomly select a vocabulary
        import random
        selected_vocab = random.choice(available_vocabs)
        
        # Check balance
        draw_price = Decimal('10.00')
        if draw_price > st.session_state.current_balance:
            return False, "Insufficient balance"
        
        # Update local state
        st.session_state.owned_vocabs.add(selected_vocab['id'])
        st.session_state.current_balance -= draw_price
        
        # Create asset record
        metadata = {
            'price_paid': float(draw_price),
            'draw_method': 'random'
        }
        
        new_asset = UserAsset(
            player_id=st.session_state.player_id,
            round_id=st.secrets['round_id'],
            asset_type='vocabulary_draw',
            content=f"Drawn vocabulary: {selected_vocab['word']}",
            used_vocabularies=json.dumps([selected_vocab['id']]),
            asset_metadata=json.dumps(metadata)
        )
        st.session_state.player_assets.append(new_asset)
        
        # Record transaction
        st.session_state.transaction_history.append({
            'type': 'draw_word',
            'vocab_id': selected_vocab['id'],
            'cost': draw_price
        })
        
        return True, selected_vocab
    except Exception as e:
        # 发生异常时回滚状态
        st.session_state.current_balance = original_balance
        st.session_state.owned_vocabs = original_owned_vocabs
        st.session_state.player_assets = original_assets
        return False, f"Transaction failed: {str(e)}"

def handle_submit_story(content_ip_rate):
    if not st.session_state.story_content:
        return False, "Please write your story content before submitting"
    
    # 检查IP费率范围是否有效
    if not content_ip_rate or content_ip_rate < 1.0 or content_ip_rate > 3.0:
        return False, "Please set a valid IP rate (between 1.0-3.0)"
    
    # 检查是否已有提交的创作
    existing_creations = [asset for asset in st.session_state.player_assets 
                          if asset.asset_type == 'user_creation']
    
    # 保存当前内容为草稿（上一版的creation变为draft）
    # 创建草稿元数据
    draft_metadata = {
        'created_at': str(datetime.now()),
        'word_count': len(st.session_state.story_content.split()),
        'is_draft': True,
        'is_from_submission': True,  # Mark this as a draft converted from submission
        'content_ip_rate': float(content_ip_rate)  # Add IP rate to metadata
    }
    
    # 创建草稿资产
    draft_asset = UserAsset(
        player_id=st.session_state.player_id,
        round_id=st.secrets['round_id'],
        asset_type='story_draft',
        content=st.session_state.story_content,
        used_vocabularies=json.dumps(list(st.session_state.owned_vocabs)),
        content_ip_rate=float(content_ip_rate),  # Add IP rate
        asset_metadata=json.dumps(draft_metadata)
    )
    
    # 添加到本地
    st.session_state.player_assets.append(draft_asset)
    
    # 记录草稿交易
    st.session_state.transaction_history.append({
        'type': 'save_draft',
        'content': st.session_state.story_content,
        'vocab_ids': list(st.session_state.owned_vocabs),
        'content_ip_rate': float(content_ip_rate),  # Add IP rate
        'metadata': draft_metadata
    })
    
    # 处理创作提交
    if existing_creations:
        # 已有提交，替换为最新版本
        creation_message = "Your previous work has been updated to the latest version."
    else:
        # 首次提交
        creation_message = "Your story has been successfully submitted! If you want to update your story, you can modify it below and submit again."
    
    # 创建提交元数据
    creation_metadata = {
        'created_at': str(datetime.now()),
        'word_count': len(st.session_state.story_content.split()),
        'is_final': True,
        'content_ip_rate': float(content_ip_rate)  # Add IP rate to metadata
    }
    
    # 创建或更新创作资产
    new_asset = UserAsset(
        player_id=st.session_state.player_id,
        round_id=st.secrets['round_id'],
        asset_type='user_creation',
        content=st.session_state.story_content,
        used_vocabularies=json.dumps(list(st.session_state.owned_vocabs)),
        content_ip_rate=float(content_ip_rate),  # Add IP rate
        asset_metadata=json.dumps(creation_metadata),
        status='submitted'  # Ensure status is submitted
    )
    
    # 如果已有创作，移除旧的创作
    for i, asset in enumerate(st.session_state.player_assets):
        if asset.asset_type == 'user_creation':
            st.session_state.player_assets.pop(i)
            break
    
    # 添加新创作到本地
    st.session_state.player_assets.append(new_asset)
    
    # 记录提交交易
    st.session_state.transaction_history.append({
        'type': 'submit_story',
        'content': st.session_state.story_content,
        'vocab_ids': list(st.session_state.owned_vocabs),
        'content_ip_rate': float(content_ip_rate),  # Add IP rate
        'is_update': bool(existing_creations)
    })
    
    # 清空故事内容 - 不直接修改session_state中的widget值，而是设置标志
    st.session_state.story_to_clear = True
    
    # 返回成功信息，包含提示消息
    return True, creation_message

def sync_to_database():
    db = next(get_db())
    try:
        # DEBUG PRINT
        print("=== STARTING DATABASE SYNC ===")
        
        # Get latest player asset information to prevent duplicate transactions
        existing_assets = UserAssetService.get_player_assets(db, st.session_state.player_id)
        
        # DEBUG PRINT
        print(f"Found {len(existing_assets)} existing assets")
        
        existing_story_contents = {
            asset.content for asset in existing_assets 
            if asset.asset_type == 'story_template' and asset.content
        }
        existing_vocab_combos = set()
        for asset in existing_assets:
            if asset.asset_type == 'vocabulary' and asset.used_vocabularies:
                try:
                    vocab_tuple = tuple(sorted(json.loads(asset.used_vocabularies)))
                    existing_vocab_combos.add(vocab_tuple)
                except:
                    pass
                
        existing_vocab_ids = UserAssetService.get_player_vocabularies(db, st.session_state.player_id)
        
        # Mark processed transactions
        processed_transactions = []
        
        # Process all transaction records
        for transaction in st.session_state.transaction_history:
            # DEBUG PRINT
            print(f"Processing transaction: {transaction['type']}")
            
            # 处理故事模板购买
            if transaction['type'] == 'purchase_story':
                combo_id = transaction.get('combo_id')
                story_id = transaction.get('story_id')
                
                # 获取combo和story数据
                combo = next((c for c in st.session_state.round_config['combinations'] if c['id'] == combo_id), None)
                if combo:
                    story = next((s for s in combo['stories'] if s['id'] == story_id), None)
                    
                    if story and story['content']:
                        # 检查是否已经存在相同内容的story_template
                        if story['content'] not in existing_story_contents:
                            # 创建元数据
                            metadata = {
                                'story_id': story_id,
                                'price_paid': float(transaction.get('cost', 0)),
                                'content_price': float(transaction.get('content_price', 0)),
                                'content_ip_rate': float(story.get('content_ip_rate', 1)),
                                'rating': story.get('rating', 0)
                            }
                            
                            # 创建story_template资产
                            UserAssetService.create_asset(
                                db=db,
                                player_id=st.session_state.player_id,
                                round_id=st.secrets['round_id'],
                                asset_type='story_template',
                                content=story['content'],
                                vocab_ids=combo['vocab_ids'],
                                metadata=metadata
                            )
                            
                            processed_transactions.append(transaction)
                            print(f"Created story_template asset with content length: {len(story['content'])}")
            
            # 处理词汇组合购买
            elif transaction['type'] == 'purchase_combination':
                combo_id = transaction.get('combo_id')
                
                # 获取combo数据
                combo = next((c for c in st.session_state.round_config['combinations'] if c['id'] == combo_id), None)
                if combo:
                    # 检查是否已经存在相同的词汇组合
                    vocab_tuple = tuple(sorted(combo['vocab_ids']))
                    if vocab_tuple not in existing_vocab_combos:
                        # 创建元数据
                        metadata = {
                            'combo_id': combo_id,
                            'price_paid': float(transaction.get('cost', 0))
                        }
                        
                        # 创建vocabulary资产
                        UserAssetService.create_asset(
                            db=db,
                            player_id=st.session_state.player_id,
                            round_id=st.secrets['round_id'],
                            asset_type='vocabulary',
                            content="",  # 空内容
                            vocab_ids=combo['vocab_ids'],
                            metadata=metadata
                        )
                        
                        processed_transactions.append(transaction)
                        print(f"Created vocabulary asset for combo: {combo_id}")
            
            # 处理随机抽取词汇
            elif transaction['type'] == 'draw_word':
                vocab_id = transaction.get('vocab_id')
                
                # 检查是否已拥有该词汇
                if vocab_id and vocab_id not in existing_vocab_ids:
                    # 获取词汇数据
                    vocab = next((v for v in st.session_state.round_config['vocabularies'] if v['id'] == vocab_id), None)
                    if vocab:
                        # 创建元数据
                        metadata = {
                            'price_paid': float(transaction.get('cost', 10.0)),
                            'draw_method': 'random'
                        }
                        
                        # 创建vocabulary_draw资产
                        UserAssetService.create_asset(
                            db=db,
                            player_id=st.session_state.player_id,
                            round_id=st.secrets['round_id'],
                            asset_type='vocabulary_draw',
                            content=f"Drawn vocabulary: {vocab['word']}",
                            vocab_ids=[vocab_id],
                            metadata=metadata
                        )
                        
                        processed_transactions.append(transaction)
                        print(f"Created vocabulary_draw asset for word: {vocab['word']}")
            
            # 处理草稿保存（包括从提交转换的草稿）
            elif transaction['type'] == 'save_draft':
                content = transaction.get('content')
                vocab_ids = transaction.get('vocab_ids', [])
                metadata = transaction.get('metadata', {})
                
                if content:
                    # 创建草稿资产
                    UserAssetService.create_asset(
                        db=db,
                        player_id=st.session_state.player_id,
                        round_id=st.secrets['round_id'],
                        asset_type='story_draft',
                        content=content,
                        vocab_ids=vocab_ids,
                        metadata=metadata
                    )
                    
                    processed_transactions.append(transaction)
            
            # 处理创作提交/更新
            elif transaction['type'] == 'submit_story':
                content = transaction.get('content')
                vocab_ids = transaction.get('vocab_ids', [])
                is_update = transaction.get('is_update', False)
                
                if content:
                    if is_update:
                        # 查找并标记旧的创作为inactive，而不是删除
                        existing_creations = [
                            asset for asset in existing_assets
                            if asset.asset_type == 'user_creation'
                        ]
                        
                        if existing_creations:
                            for creation in existing_creations:
                                # 将旧创作标记为inactive
                                UserAssetService.update_asset_status(
                                    db=db,
                                    asset_id=creation.asset_id,
                                    status='inactive'
                                )
                    
                    # 创建元数据
                    metadata = {
                        'created_at': str(datetime.now()),
                        'word_count': len(content.split()),
                        'is_final': True
                    }
                    
                    # 创建新的创作资产
                    UserAssetService.create_asset(
                        db=db,
                        player_id=st.session_state.player_id,
                        round_id=st.secrets['round_id'],
                        asset_type='user_creation',
                        content=content,
                        vocab_ids=vocab_ids,
                        metadata=metadata
                    )
                    
                    processed_transactions.append(transaction)
        
        # Ensure we use the latest story_content value - sync from temp_story_content
        if 'temp_story_content' in st.session_state and st.session_state.temp_story_content:
            st.session_state.story_content = st.session_state.temp_story_content
            
        # Update player balance
        PlayerService.update_player_balance(db, st.session_state.player_id, st.session_state.current_balance)
        
        # Remove processed transactions from transaction history
        for transaction in processed_transactions:
            if transaction in st.session_state.transaction_history:
                st.session_state.transaction_history.remove(transaction)
        
        # 标记旧的草稿为inactive，只保留最新的5个草稿
        try:
            all_drafts = [a for a in st.session_state.player_assets if a.asset_type == 'story_draft']
            # 按创建时间排序
            sorted_drafts = sorted(all_drafts, key=lambda x: x.created_at, reverse=True)
            
            # 如果草稿数量超过5个，标记旧的为inactive
            if len(sorted_drafts) > 5:
                for old_draft in sorted_drafts[5:]:
                    UserAssetService.update_asset_status(
                        db=db,
                        asset_id=old_draft.asset_id,
                        status='inactive'
                    )
                print(f"Marked {len(sorted_drafts) - 5} old drafts as inactive")
        except Exception as e:
            print(f"Error marking old drafts as inactive: {str(e)}")
        
        # 直接获取最新的数据，不使用缓存
        st.session_state.player_assets = get_player_assets(st.session_state.player_id)
        st.session_state.owned_vocabs = get_player_vocabularies(st.session_state.player_id)
        
        # DEBUG PRINT
        print(f"Refreshed assets, now have {len(st.session_state.player_assets)} assets")
        print(f"Draft count: {len([a for a in st.session_state.player_assets if a.asset_type == 'story_draft'])}")
        
        # Record last sync time
        st.session_state.last_sync_time = datetime.now()
        
        # DEBUG PRINT
        print(f"Sync completed at {st.session_state.last_sync_time}")
        
        return True, "Successfully synced to database!"
    except Exception as e:
        return False, f"Sync to database failed: {str(e)}"
    finally:
        db.close()

# Display available word combinations
def render_combinations():
    st.subheader("📜 Available Word & Combinations")

    config = st.session_state.round_config
    if not config:
        st.error("Unable to get round configuration")
        return
    
    # Create main column layout
    main_col1, main_col2 = st.columns([0.8, 0.2])
    
    # Create two columns in the left main column
    with main_col1:
        st.markdown(f"<p style='font-size: 16px;'><strong> You can purchase the following word combinations or corresponding content to create your story</strong></p>", unsafe_allow_html=True)
        
        sub_col1, sub_col2 = st.columns(2)
        
        # Display combinations in both columns
        for col_idx, sub_col in enumerate([sub_col1, sub_col2]):
            with sub_col:
                for i, combo in enumerate(config.get('combinations', [])):
                    # Only show combinations in the correct column
                    if (i % 2 == 0 and col_idx == 0) or (i % 2 == 1 and col_idx == 1):
                        # Calculate total vocabulary price
                        total_vocab_price = Decimal('0')
                        vocab_words = []
                        vocab_prices = []
                        for vocab_id in combo['vocab_ids']:
                            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                            if vocab:
                                vocab_words.append(vocab['word'])
                                vocab_prices.append(f"{vocab['word']} ${vocab['price']}")
                                total_vocab_price += Decimal(str(vocab['price']))
                        
                        # Check if already owns all words in this combination
                        already_owns_all = all(vocab_id in st.session_state.owned_vocabs for vocab_id in combo['vocab_ids'])
                        
                        # Create combination card
                        with st.expander(f"Combination {i+1}: {' + '.join(vocab_words)}  ${total_vocab_price:.2f}"):
                            st.markdown(f"<p style='font-size: 16px;'>{' + '.join(vocab_prices)}</p>", unsafe_allow_html=True)
                            
                            # Purchase word combination button
                            if st.button("Buy Word Combination", key=f"buy_combo_{combo['id']}"):
                                success, message = handle_purchase_combination(combo['id'])
                                if success:
                                    st.success(message)
                                    st.rerun()
                                else:
                                    st.error(message)
                            
                            # Sort stories by rating from high to low
                            sorted_stories = sorted(combo['stories'], key=lambda x: x['rating'], reverse=True)
                            
                            # Create index mapping table
                            sorted_to_original_index = {}
                            # Prefer to use pre-calculated mapping table
                            if 'index_mapping' in combo:
                                sorted_to_original_index = combo['index_mapping']
                            else:
                                # If no pre-calculated mapping table, then dynamically create
                                for sorted_idx, story in enumerate(sorted_stories):
                                    for original_idx, original_story in enumerate(combo['stories']):
                                        if story['id'] == original_story['id']:
                                            sorted_to_original_index[sorted_idx] = original_idx
                                            break
                            
                            # Display each story's content
                            for j, story in enumerate(sorted_stories):
                                # Calculate content additional price
                                content_price = total_vocab_price * (Decimal(str(story['content_ip_rate'])) - Decimal('1'))
                                
                                # Calculate missing vocabulary price
                                missing_vocab_price = Decimal('0')
                                for vocab_id in combo['vocab_ids']:
                                    vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                                    if vocab and vocab_id not in st.session_state.owned_vocabs:
                                        missing_vocab_price += Decimal(str(vocab['price']))
                                
                                # Final price = content additional price + missing vocabulary price
                                final_price = content_price + missing_vocab_price
                                
                                st.markdown(f"<p style='font-size: 16px;'><strong>Story {j+1}</strong></p>", unsafe_allow_html=True)
                                st.markdown(f"Rating: {story['rating']} | IP Rate set by the author: {story['content_ip_rate']}")
                                
                                # Display price details
                                st.markdown(f"Story extra content price: ${content_price:.2f}")
                                if missing_vocab_price > 0:
                                    st.markdown(f"Missing vocabulary price: ${missing_vocab_price:.2f}")
                                    st.markdown(f"<strong>Total price to pay: ${final_price:.2f}</strong>", unsafe_allow_html=True)
                                    button_text = f"Buy Missing Words & Content: ${final_price:.2f}"
                                else:
                                    # If already owns all vocabularies, display only content price
                                    st.markdown(f"<strong>Total price to pay: ${content_price:.2f}</strong>", unsafe_allow_html=True)
                                    button_text = f"Buy Story Content Only: ${content_price:.2f}"
                                
                                # Check if this story is already owned
                                already_owns_story = any(
                                    s.content == story['content'] 
                                    for s in st.session_state.player_assets 
                                    if s.content
                                )
                                    
                                if already_owns_story:
                                    st.markdown(f"<p style='color: green;'>✓ You own this story</p>", unsafe_allow_html=True)
                                
                                if st.button(button_text, key=f"buy_content_{combo['id']}_{j}"):
                                    if already_owns_story:
                                        st.error("You have already purchased this story")
                                    else:
                                        original_story_index = sorted_to_original_index[j]
                                        success, message = handle_purchase_story_content(combo['id'], original_story_index)
                                        if success:
                                            st.success(message)
                                            st.rerun()
                                        else:
                                            st.error(message)
                                
                                #st.divider()
    
    # Display random word draw button in right main column
    with main_col2:
        st.markdown(f"<p style='font-size: 16px;'><strong>Or, spend $10.00 to get a random new word from the vocabulary library</strong></p>", unsafe_allow_html=True)
        if st.button("Draw Word", key="draw_vocab"):
            success, result = handle_draw_random_word()
            if success:
                st.success(f"Congratulations! You drew the word: {result['word']}, price: ${result['price']:.2f}")
                st.rerun()
            else:
                st.error(result)

# Left sidebar - Statistics
def render_left_sidebar():
    st.subheader("📊 Statistics")
    player = st.session_state.player_info
    if player:
        st.markdown(f"<p style='font-size: 16px;'><strong>Current Balance: ${st.session_state.current_balance:.2f}</strong></p>", unsafe_allow_html=True)
        
        # 使用安全的属性访问方式
        try:
            current_round = getattr(player, 'current_round', "N/A")
            player_id = getattr(player, 'player_id', st.session_state.player_id)
            
            st.markdown(f"<p style='font-size: 16px;'>Current Round: {current_round}</p>", unsafe_allow_html=True)
            st.markdown(f"<p style='font-size: 16px;'>Player ID: {player_id}</p>", unsafe_allow_html=True)
        except Exception as e:
            # 回退到显示会话状态中的信息
            st.markdown(f"<p style='font-size: 16px;'>Player ID: {st.session_state.player_id}</p>", unsafe_allow_html=True)
            print(f"Error accessing player attributes: {e}")
    else:
        st.warning("Player information not found")
        st.markdown(f"<p style='font-size: 16px;'>Player ID: {st.session_state.player_id}</p>", unsafe_allow_html=True)
    
    # Add empty lines
    for _ in range(4):
        st.write("")
    
    # Save draft button and story check logic
    check_save, submit_story = st.columns(2)
    with check_save:
        save_button = st.button("Check & Save")
    with submit_story:
        submit_button = st.button("Submit Story", type="primary", use_container_width=True)

    # 添加导航按钮，仅在用户已提交故事后显示
    existing_creations = [asset for asset in st.session_state.player_assets 
                          if asset.asset_type == 'user_creation']
    if existing_creations:
        if st.button("⭐ Go Rate Other Stories", type="primary" , use_container_width=True):
            st.switch_page("pages/3_Score_Story_Page.py")

    if save_button:
        # Handle saving draft
        with st.spinner('Saving draft...'):
            # First check if there's any content
            if not st.session_state.story_content:
                st.warning("No content to save!")
            else:
                # Create save container for feedback
                save_container = st.empty()
                
                # 创建草稿元数据
                draft_metadata = {
                    'created_at': str(datetime.now()),
                    'word_count': len(st.session_state.story_content.split()),
                    'is_draft': True
                }
                
                # 创建草稿资产
                draft_asset = UserAsset(
                    player_id=st.session_state.player_id,
                    round_id=st.secrets['round_id'],
                    asset_type='story_draft',
                    content=st.session_state.story_content,
                    used_vocabularies=json.dumps(list(st.session_state.owned_vocabs)),
                    asset_metadata=json.dumps(draft_metadata)
                )
                
                # 添加到本地
                st.session_state.player_assets.append(draft_asset)
                
                # 记录草稿交易
                st.session_state.transaction_history.append({
                    'type': 'save_draft',
                    'content': st.session_state.story_content,
                    'vocab_ids': list(st.session_state.owned_vocabs),
                    'metadata': draft_metadata
                })
                
                success = True
                message = "Draft saved successfully"
                
                # 然后同步到数据库
                try:
                    # 同步到数据库
                    sync_success, sync_message = sync_to_database()
                    if not sync_success:
                        success = False
                        message = f"Error syncing to database: {sync_message}"
                except Exception as e:
                    success = False
                    message = f"Error: {str(e)}"
                
                # 然后检查故事规则
                if success:
                    # 更新故事检测逻辑
                    # 1. 分割成句子
                    sentences = [s.strip() for s in re.split(r'[.!?]+', st.session_state.story_content) if s.strip()]
                    
                    # 获取用户拥有的词汇列表
                    owned_vocab_words = []
                    owned_vocab_dict = {}
                    for vocab_id in st.session_state.owned_vocabs:
                        vocab = next((v for v in st.session_state.round_config['vocabularies'] if v['id'] == vocab_id), None)
                        if vocab:
                            owned_vocab_words.append(vocab['word'])
                            owned_vocab_dict[vocab['word']] = vocab_id
                    
                    # 2. 检查每个句子是否包含且仅包含一个单词或词组
                    sentence_word_matches = {}
                    used_words = set()
                    for i, sentence in enumerate(sentences):
                        sentence_matches = []
                        
                        for word in owned_vocab_words:
                            if word.lower() in sentence.lower():
                                sentence_matches.append(word)
                                
                        # 检查当前句子匹配的词汇数量
                        if len(sentence_matches) == 0:
                            error_msg = f"Sentence {i+1} does not contain any purchased words or phrases."
                            st.session_state.last_check_result = {
                                'status': 'error',
                                'message': error_msg
                            }
                            save_container.error(error_msg)
                            return
                        elif len(sentence_matches) > 1:
                            error_msg = f"Sentence {i+1} contains multiple words or phrases: {', '.join(sentence_matches)}. Each sentence should contain only one word or phrase."
                            st.session_state.last_check_result = {
                                'status': 'error',
                                'message': error_msg
                            }
                            save_container.error(error_msg)
                            return
                        
                        # 检查词汇是否已在其他句子中使用
                        word = sentence_matches[0]
                        if word in used_words:
                            error_msg = f"Word or phrase '{word}' is used in multiple sentences. Each word or phrase should be used in only one sentence."
                            st.session_state.last_check_result = {
                                'status': 'error',
                                'message': error_msg
                            }
                            save_container.error(error_msg)
                            return
                        
                        # 添加到已使用词汇和句子匹配字典
                        used_words.add(word)
                        sentence_word_matches[i] = word
                    
                    # 3. 检查所有词汇是否都被使用（句子数量 = 词汇数量）
                    if len(sentences) != len(owned_vocab_words):
                        if len(sentences) < len(owned_vocab_words):
                            error_msg = f"You own {len(owned_vocab_words)} words or phrases, but there are only {len(sentences)} sentences. Each word or phrase must be used in a sentence."
                        else:
                            error_msg = f"You own {len(owned_vocab_words)} words or phrases, but there are {len(sentences)} sentences. Each sentence must use exactly one word or phrase."
                        st.session_state.last_check_result = {
                            'status': 'error',
                            'message': error_msg
                        }
                        save_container.error(error_msg)
                        return
                    
                    # 4. 检查是否所有词汇都被使用
                    unused_words = set(owned_vocab_words) - used_words
                    if unused_words:
                        error_msg = f"The following words or phrases are not used: {', '.join(unused_words)}. All words or phrases must be used."
                        st.session_state.last_check_result = {
                            'status': 'error',
                            'message': error_msg
                        }
                        save_container.error(error_msg)
                        return
                        
                    # 所有检查通过
                    success_msg = "Story check passed! Each sentence uses one word or phrase, and all words or phrases are used."
                    st.session_state.last_check_result = {
                        'status': 'success',
                        'message': success_msg
                    }
                
                # 显示保存结果 - 只有在所有检查通过后才显示成功保存的消息
                if success:
                    save_container.success("Your draft has been saved successfully.")
                else:
                    save_container.error(f"Error saving draft: {message}")

    # 修改提交故事的处理逻辑，只设置标志但不立即提交
    if submit_button:
        # 检查故事内容是否存在
        if not st.session_state.story_content:
            st.error("Please write your story content before submitting")
        else:
            # 获取用户拥有的词汇列表
            owned_vocab_words = []
            owned_vocab_dict = {}
            for vocab_id in st.session_state.owned_vocabs:
                vocab = next((v for v in st.session_state.round_config['vocabularies'] if v['id'] == vocab_id), None)
                if vocab:
                    owned_vocab_words.append(vocab['word'])
                    owned_vocab_dict[vocab['word']] = vocab_id
            
            # 使用StoryValidationService验证故事
            validation_result = StoryValidationService.validate_story(
                st.session_state.story_content, 
                owned_vocab_words
            )
            
            if validation_result["valid"]:
                # 设置会话状态标志，表示准备提交故事（会触发IP费率设置界面显示）
                st.session_state.show_ip_rate_setting = True
                # 使用rerun确保IP费率设置界面显示
                st.rerun()
            else:
                st.error(validation_result["message"])
                # 保存检查结果到session_state
                st.session_state.last_check_result = {
                    'status': 'error',
                    'message': validation_result["message"]
                }

# Center area - Story creation
def render_center_content():
    # 如果需要清空故事内容（提交后）
    if 'story_to_clear' in st.session_state and st.session_state.story_to_clear:
        st.session_state.story_content = ""
        # 初始化临时内容为空字符串，但不直接修改temp_story_content
        if 'temp_story_content' not in st.session_state:
            st.session_state.temp_story_content = ""
        # 移除清除标志
        st.session_state.pop('story_to_clear', None)
    
    # 添加IP费率部分，仅在准备提交时显示
    if 'show_ip_rate_setting' in st.session_state and st.session_state.show_ip_rate_setting:
        st.subheader("Set Content IP Rate")
        st.info("Please set the IP rate for your story. A higher rate will increase the price of your story in the next round of the game but may reduce the chance of being selected.")
        
        # 使用slider设置IP费率，不设置默认值强制用户选择
        content_ip_rate = st.slider(
            "Content IP Rate (Required)",
            min_value=1.0,
            max_value=3.0,
            value=None,  # No default value, forcing user to choose
            step=0.1,
            help="Set the IP rate for your story (1.0-3.0). Higher rates mean more expensive copyright fees."
        )
        
        if not content_ip_rate:
            st.warning("Please set the content IP rate before submitting")
            can_submit = False
        else:
            st.write(f"You've set the IP rate to: {content_ip_rate:.1f}. This means players in the next round will pay {content_ip_rate:.1f} times the base price to purchase your story.")
            can_submit = True
        
        # 将确认提交和取消提交按钮放在同一行
        col1, col2 = st.columns(2)
        with col1:
            cancel_button = st.button("Cancel", use_container_width=True)
        with col2:
            confirm_button = st.button("Confirm Submission", disabled=not can_submit, use_container_width=True, type="primary")
        
        if confirm_button and can_submit:
            # 处理提交
            success, message = handle_submit_story(content_ip_rate)
            if success:
                # 然后同步到数据库
                sync_result, _ = sync_to_database()
                if sync_result:
                    st.success(message)  # 显示自定义的提交成功消息
                    # 保存检查结果到session_state
                    st.session_state.last_check_result = {
                        'status': 'success',
                        'message': message
                    }
                # 重置提交标志
                st.session_state.show_ip_rate_setting = False
                st.rerun()
            else:
                st.error(message)
                # 保存检查结果到session_state
                st.session_state.last_check_result = {
                    'status': 'error',
                    'message': message
                }
        
        if cancel_button:
            # 重置提交标志
            st.session_state.show_ip_rate_setting = False
            st.rerun()
    else:
        # 常规故事创建界面
        st.subheader("✍️ Story Creation")
        
        # 安全访问player_info
        try:
            player = st.session_state.player_info
            if not player:
                st.error("Player does not exist, please refresh the page and try again")
                return
        except Exception as e:
            print(f"Error accessing player_info: {e}")
            # 如果无法访问player_info，继续执行其他逻辑
        
        # 不再访问player的属性，直接使用会话状态中的数据
        
        # Check if any vocabulary is selected
        if not st.session_state.owned_vocabs:
            st.info("Please obtain vocabulary through drawing or purchasing first, then start creating your story")
            return
        
        # 显示上次检查结果（如果有）
        if 'last_check_result' in st.session_state:
            if st.session_state.last_check_result.get('status') == 'success':
                st.success(st.session_state.last_check_result.get('message', 'Story check passed!'))
            elif st.session_state.last_check_result.get('status') == 'error':
                st.error(st.session_state.last_check_result.get('message', 'Story check failed.'))
        
        # Define function to update story content
        def update_story_content():
            # Ensure temporary content is correctly saved to session_state
            previous_content = st.session_state.story_content if 'story_content' in st.session_state else ""
            st.session_state.story_content = st.session_state.temp_story_content
            
            # 使用difflib计算内容相似度，但不再触发自动保存
            if previous_content and st.session_state.story_content:
                # 使用SequenceMatcher计算文本相似度
                similarity_ratio = difflib.SequenceMatcher(None, previous_content, st.session_state.story_content).ratio()
                print(f"Content similarity (difflib): {similarity_ratio:.2f}")
            
            print(f"Story content updated from {len(previous_content)} to {len(st.session_state.story_content)} characters")
            
            # Force display debug info
            if 'story_content' in st.session_state and st.session_state.story_content:
                print(f"Updated content: '{st.session_state.story_content[:30]}...'")
        
        # Initialize temporary storage to ensure it always has a value
        if 'temp_story_content' not in st.session_state:
            st.session_state.temp_story_content = st.session_state.story_content
        
        # Story content - use on_change callback and key parameter to ensure content is correctly saved
        st.text_area(
            """Create your science fiction story here... 
            \nClick the "Check & Save" button to test if your story meets the requirements and save a draft. 
            \nWhen finished, click the "Submit Story" button to submit your work.""", 
            height=200,
            value=st.session_state.story_content,
            placeholder="Create a science fiction story using your acquired vocabulary...",
            help="Each sentence must contain exactly one word or phrase from your acquired vocabulary",
            key="temp_story_content",
            on_change=update_story_content
        )

# Right sidebar - Purchased content
def render_right_sidebar():

    st.markdown("#### 📝 Purchased   Vocabulary")
    
    config = st.session_state.round_config
    if not config:
        st.error("Unable to get round configuration")
        return
    
    # Display owned vocabularies
    if st.session_state.owned_vocabs:
        
        word_count = 0
        
        # 获取词汇并按字母顺序排序
        vocab_words = []
        for vocab_id in st.session_state.owned_vocabs:
            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
            if vocab:
                vocab_words.append((vocab['word'], vocab['price']))
                word_count += 1
        
        # 按字母顺序排序
        vocab_words.sort(key=lambda x: x[0].lower())
        
        # 显示排序后的词汇
        for word, price in vocab_words:
            st.write(f"- {word} (Price: ${price:.2f})")
            
        st.markdown(f"Total owned words: {word_count}")
    else:
        st.info("No vocabulary selected yet")

# Main function
def main():
    init_session_state()
    
    # 初始化IP费率设置标志
    if 'show_ip_rate_setting' not in st.session_state:
        st.session_state.show_ip_rate_setting = False
    
    # Upper part: display available word combinations
    render_combinations()
    
    # Lower part: left-center-right layout
    left_col, center_col, right_col = st.columns([0.25, 0.5, 0.25])
    
    with left_col:
        render_left_sidebar()
    with center_col:
        render_center_content()
    with right_col:
        render_right_sidebar()
    
    # Add content sections below
    #st.divider()
    
    # Story Templates section
    st.markdown("### 📖 Purchased Story Templates")
    story_templates = [asset for asset in st.session_state.player_assets 
                        if asset.asset_type == 'story_template' and asset.content]
    
    if story_templates:
        # 按评分从高到低排序
        try:
            def get_rating(asset):
                try:
                    if asset.asset_metadata:
                        metadata = json.loads(asset.asset_metadata)
                        return float(metadata.get('rating', 0))
                    return 0
                except:
                    return 0
            
            sorted_templates = sorted(story_templates, key=get_rating, reverse=True)
        except Exception as e:
            st.error(f"Error sorting templates: {str(e)}")
            sorted_templates = story_templates
        
        for asset in sorted_templates:
            # Get story combo information
            combo = None
            for c in st.session_state.round_config.get('combinations', []):
                if set(json.loads(asset.used_vocabularies)) == set(c['vocab_ids']):
                    combo = c
                    break
            
            if combo:
                # Find corresponding story content
                story_data = next((s for s in combo['stories'] if s['content'] == asset.content), None)
                
                # 获取词汇名称
                vocab_names = []
                if asset.used_vocabularies:
                    try:
                        vocab_ids = json.loads(asset.used_vocabularies)
                        for vocab_id in vocab_ids:
                            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                            if vocab:
                                vocab_names.append(vocab['word'])
                    except Exception as e:
                        print(f"Error getting story template vocabulary names: {e}")
                
                # 按字母顺序排序词汇
                vocab_names.sort(key=lambda x: x.lower())
                vocab_label = " + ".join(vocab_names) if vocab_names else "Unknown vocabularies"
                    
                # Try to get rating and price from metadata
                rating = ""
                price_info = ""
                try:
                    metadata = json.loads(asset.asset_metadata) if asset.asset_metadata else {}
                    if 'rating' in metadata:
                        rating = f"Rating: {metadata['rating']}"
                    if 'price_paid' in metadata:
                        price_info = f"Price paid: ${metadata['price_paid']:.2f}"
                except:
                    pass
                
                # 显示标题
                header_parts = []
                if rating:
                    header_parts.append(rating)
                if price_info:
                    header_parts.append(price_info)
                
                header = " | ".join(header_parts)
                st.markdown(f"**Story Template: {vocab_label}**")
                if header:
                    st.markdown(f"*{header}*")
                
                # 显示内容
                st.write(f"{asset.content}")
                st.divider()
            else:
                # 无法找到匹配的combo时，仍然显示内容
                st.markdown(f"**Story Template**")
                st.write(f"{asset.content}")
                st.divider()
    else:
        st.info("No story templates purchased yet")
    
    # My Drafts section
    st.markdown("### 📝 My Drafts")
    
    story_drafts = [asset for asset in st.session_state.player_assets 
                    if asset.asset_type == 'story_draft' and asset.content]
    
    if story_drafts:
        # 按创建时间排序，使用metadata中的created_at而不是对象属性
        try:
            # 定义排序函数
            def get_creation_time(asset):
                try:
                    if asset.asset_metadata:
                        metadata = json.loads(asset.asset_metadata)
                        if 'created_at' in metadata:
                            # 尝试转换为datetime对象
                            try:
                                return datetime.fromisoformat(metadata['created_at'].replace('Z', '+00:00'))
                            except:
                                return datetime.now()  # 如果解析失败，返回当前时间
                    # 如果没有元数据或没有created_at字段，使用asset.created_at（如果存在）
                    return getattr(asset, 'created_at', datetime.now())
                except:
                    return datetime.now()  # 出错时返回当前时间
            
            # 使用自定义排序函数
            sorted_drafts = sorted(story_drafts, key=get_creation_time, reverse=True)
        except Exception as e:
            st.error(f"Error sorting drafts: {str(e)}")
            sorted_drafts = story_drafts  # Use unsorted if sorting fails
            
        for i, asset in enumerate(sorted_drafts[:5]):  # 显示最新的5个草稿，而不是只有1个
            try:
                metadata = json.loads(asset.asset_metadata) if asset.asset_metadata else {}
                created_time = metadata.get('created_at', 'Unknown time')
                
                # 获取使用的词汇列表
                vocab_names = []
                if asset.used_vocabularies:
                    try:
                        vocab_ids = json.loads(asset.used_vocabularies)
                        config = st.session_state.round_config
                        
                        # 获取词汇名称
                        for vocab_id in vocab_ids:
                            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                            if vocab:
                                vocab_names.append(vocab['word'])
                    except Exception as e:
                        print(f"Error getting vocabulary names: {e}")
                
                # 按字母顺序排序词汇名称
                vocab_names.sort(key=lambda x: x.lower())
                
                # 生成词汇标签
                vocab_label = " + ".join(vocab_names) if vocab_names else "No vocabularies"
                    
                # 创建标签（已移除auto-saved相关逻辑）
                draft_label = f"**(Saved: {created_time}) {vocab_label}**"
                    
                st.markdown(draft_label)
                st.write(f"{asset.content}")
               
            except Exception as e:
                st.error(f"Error displaying draft {i+1}: {str(e)}")
    else:
        st.info("No drafts saved yet")
    
    st.divider()

    # My Creations section - 修改显示为My Submitted Story
    st.markdown("### 🖊️ My Submitted Story")
    user_creations = [asset for asset in st.session_state.player_assets 
                        if asset.asset_type == 'user_creation' and asset.content]
    
    if user_creations:
        for asset in user_creations:
            st.markdown("**My Submitted Story**")
            
            # 添加提交时间和IP费率显示
            try:
                metadata = json.loads(asset.asset_metadata) if asset.asset_metadata else {}
                created_at = metadata.get('created_at', 'Unknown time')
                content_ip_rate = asset.content_ip_rate if asset.content_ip_rate else 1.0
                
                # 格式化创建时间
                try:
                    created_datetime = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    formatted_time = created_datetime.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    formatted_time = created_at
                
                # 显示故事元信息
                st.write(f"Submission time: {formatted_time} | IP rate: {content_ip_rate:.1f}")
            except Exception as e:
                print(f"Error parsing metadata: {e}")
            
            # 显示故事内容
            st.write(f"{asset.content}")
            st.divider()
    else:
        st.info("No stories submitted yet")

if __name__ == "__main__":
    main()