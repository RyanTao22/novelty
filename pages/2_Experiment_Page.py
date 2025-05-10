import streamlit as st
from typing import List, Dict
from models import Player, UserAsset, GameRound
from service import PlayerService, UserAssetService, GameRoundService
from config import get_db
import json
import logging
from decimal import Decimal
import re
from datetime import datetime
import time

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
        
    # Get database session
    db = next(get_db())
    try:
        # Load round configuration
        st.session_state.round_config = GameRoundService.get_round_config(db, 1)
        
        # Load or create player information
        player = PlayerService.get_player(db, st.session_state.player_id)
        if not player:
            player = PlayerService.create_player(db, st.session_state.player_id)
        st.session_state.player_info = player
        
        # Initialize balance and owned vocabulary set
        st.session_state.initial_balance = Decimal(str(st.session_state.round_config['initial_balance']))
        st.session_state.current_balance = st.session_state.player_info.total_earnings
        
        # Get all vocabularies owned by the player
        st.session_state.owned_vocabs = UserAssetService.get_player_vocabularies(db, st.session_state.player_id)
        
        # Load player's existing assets
        st.session_state.player_assets = UserAssetService.get_player_assets(db, st.session_state.player_id)
        
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
    finally:
        db.close()

# Local transaction handling functions
def handle_purchase_combination(combo_id: str):
    combo = next((c for c in st.session_state.round_config['combinations'] if c['id'] == combo_id), None)
    if not combo:
        return False, "Combination not found"
    
    # Check if all vocabularies are already owned
    if all(vocab_id in st.session_state.owned_vocabs for vocab_id in combo['vocab_ids']):
        return False, "You already own all words in this combination"
    
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
        round_id=1,
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

def handle_purchase_story_content(combo_id: str, story_index: int):
    print(f"DEBUG - Purchase story content started: combo_id={combo_id}, story_index={story_index}")
    
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
        round_id=1,
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

def handle_draw_random_word():
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
        round_id=1,
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

def handle_submit_story():
    if not st.session_state.story_content:
        return False, "Please enter story content first"
    
    # Create user story asset
    metadata = {
        'created_at': str(datetime.now()),
        'word_count': len(st.session_state.story_content.split())
    }
    
    new_asset = UserAsset(
        player_id=st.session_state.player_id,
        round_id=1,
        asset_type='user_creation',
        content=st.session_state.story_content,
        used_vocabularies=json.dumps(list(st.session_state.owned_vocabs)),
        asset_metadata=json.dumps(metadata)
    )
    
    # Add to local
    st.session_state.player_assets.append(new_asset)
    
    # Record transaction
    st.session_state.transaction_history.append({
        'type': 'submit_story',
        'content': st.session_state.story_content,
        'vocab_ids': list(st.session_state.owned_vocabs)
    })
    
    # Clear story content - also clear content in both storage locations
    content_to_submit = st.session_state.story_content  # Save one copy for logging
    st.session_state.story_content = ""
    if 'temp_story_content' in st.session_state:
        st.session_state.temp_story_content = ""
    
    # Log
    print(f"Story submitted successfully, content length: {len(content_to_submit)} characters")
    
    return True, "Story submitted successfully"

def sync_to_database():
    db = next(get_db())
    try:
        # Get latest player asset information to prevent duplicate transactions
        existing_assets = UserAssetService.get_player_assets(db, st.session_state.player_id)
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
            if transaction['type'] == 'purchase_story':
                # Purchase story
                combo_id = transaction['combo_id']
                story_index = transaction.get('story_index', 0)
                
                # Get combo and story information
                combo = next((c for c in st.session_state.round_config['combinations'] if c['id'] == combo_id), None)
                if combo and story_index < len(combo['stories']):
                    story = combo['stories'][story_index]
                    
                    # Check if this story is already in the database
                    if story['content'] in existing_story_contents:
                        processed_transactions.append(transaction)
                        continue
                    
                    # Create metadata
                    metadata = {
                        'story_id': story['id'],
                        'price_paid': float(transaction['cost']),
                        'content_price': float(transaction['content_price']),
                        'content_ip_rate': float(story['content_ip_rate']),
                        'rating': story.get('rating')
                    }
                    
                    # Create asset record
                    UserAssetService.create_asset(
                        db=db,
                        player_id=st.session_state.player_id,
                        round_id=1,
                        asset_type='story_template',
                        content=story['content'],
                        vocab_ids=combo['vocab_ids'],
                        metadata=metadata
                    )
                    
                    existing_story_contents.add(story['content'])
                    processed_transactions.append(transaction)
                
            elif transaction['type'] == 'purchase_combination':
                # Purchase vocabulary combination
                combo_id = transaction['combo_id']
                combo = next((c for c in st.session_state.round_config['combinations'] if c['id'] == combo_id), None)
                if combo:
                    # Check if this combination is already in the database
                    vocab_tuple = tuple(sorted(combo['vocab_ids']))
                    if vocab_tuple in existing_vocab_combos:
                        processed_transactions.append(transaction)
                        continue
                        
                    # Create metadata
                    metadata = {
                        'combo_id': combo['id'],
                        'price_paid': float(transaction['cost'])
                    }
                    
                    # Create asset record
                    UserAssetService.create_asset(
                        db=db,
                        player_id=st.session_state.player_id,
                        round_id=1,
                        asset_type='vocabulary',
                        content="",  # Empty content
                        vocab_ids=combo['vocab_ids'],
                        metadata=metadata
                    )
                    
                    existing_vocab_combos.add(vocab_tuple)
                    processed_transactions.append(transaction)
                
            elif transaction['type'] == 'draw_word':
                # Draw vocabulary
                vocab_id = transaction.get('vocab_id')
                if vocab_id:
                    # Check if this vocabulary is already in the database
                    if vocab_id in existing_vocab_ids:
                        processed_transactions.append(transaction)
                        continue
                        
                    vocab = next((v for v in st.session_state.round_config['vocabularies'] if v['id'] == vocab_id), None)
                    if vocab:
                        # Create metadata
                        metadata = {
                            'price_paid': float(transaction['cost']),
                            'draw_method': 'random'
                        }
                        
                        # Create asset record
                        UserAssetService.create_asset(
                            db=db,
                            player_id=st.session_state.player_id,
                            round_id=1,
                            asset_type='vocabulary_draw',
                            content=f"Drawn vocabulary: {vocab['word']}",
                            vocab_ids=[vocab_id],
                            metadata=metadata
                        )
                        
                        existing_vocab_ids.add(vocab_id)
                        processed_transactions.append(transaction)
            
            elif transaction['type'] == 'submit_story':
                # Submit user created story
                content = transaction.get('content')
                vocab_ids = transaction.get('vocab_ids', [])
                if content:
                    # Check if this content is already in the database (simple check)
                    content_exists = any(
                        asset.content == content and asset.asset_type == 'user_creation'
                        for asset in existing_assets
                    )
                    
                    if content_exists:
                        processed_transactions.append(transaction)
                        continue
                        
                    # Create metadata
                    metadata = {
                        'created_at': str(datetime.now()),
                        'word_count': len(content.split())
                    }
                    
                    # Create asset record
                    UserAssetService.create_asset(
                        db=db,
                        player_id=st.session_state.player_id,
                        round_id=1,
                        asset_type='user_creation',
                        content=content,
                        vocab_ids=vocab_ids,
                        metadata=metadata
                    )
                    
                    processed_transactions.append(transaction)
        
        # Ensure we use the latest story_content value - sync from temp_story_content
        if 'temp_story_content' in st.session_state and st.session_state.temp_story_content:
            st.session_state.story_content = st.session_state.temp_story_content
        
        # Save current story content as draft
        if st.session_state.story_content:
            # Iterate existing drafts, find content that is the same or similar
            draft_exists = False
            for asset in existing_assets:
                if asset.asset_type == 'story_draft':
                    # If content is exactly the same, no need to create new draft
                    if asset.content == st.session_state.story_content:
                        draft_exists = True
                        break
                    # If content similarity is high (e.g., only a few characters different)
                    # It can also be considered the same draft
                    # Here we use simple length comparison instead of detailed similarity calculation
                    content_similarity = min(len(asset.content), len(st.session_state.story_content)) / max(len(asset.content), len(st.session_state.story_content)) if max(len(asset.content), len(st.session_state.story_content)) > 0 else 0
                    if content_similarity > 0.9:  # If similarity is greater than 90%
                        # Update existing draft content
                        UserAssetService.update_asset(
                            db=db,
                            asset_id=asset.asset_id,
                            content=st.session_state.story_content
                        )
                        draft_exists = True
                        break
            
            if not draft_exists:
                # Create metadata
                metadata = {
                    'created_at': str(datetime.now()),
                    'word_count': len(st.session_state.story_content.split()),
                    'is_draft': True
                }
                
                # Create asset record
                UserAssetService.create_asset(
                    db=db,
                    player_id=st.session_state.player_id,
                    round_id=1,
                    asset_type='story_draft',
                    content=st.session_state.story_content,
                    vocab_ids=list(st.session_state.owned_vocabs),
                    metadata=metadata
                )
        
        # Update player balance
        PlayerService.update_player_balance(db, st.session_state.player_id, st.session_state.current_balance)
        
        # Remove processed transactions from transaction history
        for transaction in processed_transactions:
            if transaction in st.session_state.transaction_history:
                st.session_state.transaction_history.remove(transaction)
        
        # Refresh player asset list
        st.session_state.player_assets = UserAssetService.get_player_assets(db, st.session_state.player_id)
        
        # Record last sync time
        st.session_state.last_sync_time = datetime.now()
        
        return True, "Successfully synced to database! Your story draft has been saved."
    except Exception as e:
        return False, f"Sync to database failed: {str(e)}"
    finally:
        db.close()

# Display available word combinations
def render_combinations():
    st.subheader("📜 Available Word Combinations")

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
        st.markdown(f"<p style='font-size: 16px;'>Current Round: {player.current_round}</p>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-size: 16px;'>Player ID: {player.player_id}</p>", unsafe_allow_html=True)
    else:
        st.warning("Player information not found")
    
    # Add empty lines
    for _ in range(4):
        st.write("")
    
    # Button area
    col1, col2 = st.columns(2)
    
    with col1:
        check_story = st.button("Check Story")
    with col2:
        submit_story = st.button("Submit", type="primary")
    
    # 在按钮下方显示检查结果
    if check_story:
        if not st.session_state.story_content:
            st.error("Please enter story content first")
        else:
            config = st.session_state.round_config
            if not config:
                st.error("Unable to get round configuration")
            else:
                # Split sentences, supporting multiple sentence ending symbols
                sentences = [s.strip() for s in re.split(r'[.!?。！？]', st.session_state.story_content) if s.strip()]
                
                # Check if sentence count matches vocabulary count
                if len(sentences) != len(st.session_state.owned_vocabs):
                    # Get vocabulary name list and ID
                    vocab_dict = {}
                    for vocab_id in st.session_state.owned_vocabs:
                        vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                        if vocab:
                            vocab_dict[vocab_id] = vocab['word']
                    
                    if len(sentences) < len(st.session_state.owned_vocabs):
                        # Check which words are not used
                        # First simulate matching existing sentences
                        used_vocab_ids = set()
                        for sentence in sentences:
                            for vocab_id, word in vocab_dict.items():
                                if word.lower() in sentence.lower() and vocab_id not in used_vocab_ids:
                                    used_vocab_ids.add(vocab_id)
                                    break
                        
                        # Find unused words
                        missing_words = [word for vocab_id, word in vocab_dict.items() if vocab_id not in used_vocab_ids]
                        missing_str = ", ".join(missing_words)
                        
                        st.error(f"Your story needs {len(st.session_state.owned_vocabs)} sentences, but only has {len(sentences)}. Missing words in sentences: {missing_str}")
                    else:
                        st.error(f"Your story has {len(sentences)} sentences, but you only have {len(st.session_state.owned_vocabs)} vocabulary words. Each sentence should use one vocabulary word.")
                else:
                    # Check if each sentence contains any vocabulary
                    used_vocabs = set()
                    sentence_matches = []
                    
                    for i, sentence in enumerate(sentences):
                        sentence_contains = False
                        matched_vocab = None
                        for vocab_id in st.session_state.owned_vocabs:
                            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                            if vocab and vocab['word'] in sentence.lower() and vocab_id not in used_vocabs:
                                used_vocabs.add(vocab_id)
                                sentence_contains = True
                                matched_vocab = vocab['word']
                                break
                        
                        if not sentence_contains:
                            # Find unused words
                            unused_vocabs = []
                            for vocab_id in st.session_state.owned_vocabs:
                                if vocab_id not in used_vocabs:
                                    vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
                                    if vocab:
                                        unused_vocabs.append(vocab['word'])
                            
                            st.error(f"Sentence {i+1} does not contain any unused vocabulary. Available words you can use: {', '.join(unused_vocabs)}")
                            return
                        else:
                            sentence_matches.append((i+1, sentence, matched_vocab))
                    
                    # Display matching results
                    st.success("Story check passed!")
    
    if submit_story:
        success, message = sync_to_database()
        if success:
            # 重新加载用户创作内容
            db = next(get_db())
            try:
                st.session_state.player_assets = UserAssetService.get_player_assets(db, st.session_state.player_id)
            finally:
                db.close()
            st.success(message)
            st.rerun()
        else:
            st.error(message)

# Center area - Story creation
def render_center_content():
    st.subheader("✍️ Story Creation")
    
    player = st.session_state.player_info
    if not player:
        st.error("Player does not exist, please refresh the page and try again")
        return
    
    # Check if any vocabulary is selected
    if not st.session_state.owned_vocabs:
        st.info("Please obtain vocabulary through drawing or purchasing first, then start creating your story")
        return
    
    # Display last saved draft information
    story_drafts = [asset for asset in st.session_state.player_assets 
                    if asset.asset_type == 'story_draft' and asset.content]
    if story_drafts and st.session_state.story_content:
        latest_draft = sorted(story_drafts, key=lambda x: x.created_at, reverse=True)[0]
        try:
            metadata = json.loads(latest_draft.asset_metadata) if latest_draft.asset_metadata else {}
            created_time = metadata.get('created_at', 'Unknown time')
            st.info(f"Continue editing last saved draft (Saved time: {created_time})")
        except:
            pass
    
    # Define function to update story content
    def update_story_content():
        # Ensure temporary content is correctly saved to session_state
        st.session_state.story_content = st.session_state.temp_story_content
    
    # Initialize temporary storage to ensure it always has a value
    if 'temp_story_content' not in st.session_state:
        st.session_state.temp_story_content = st.session_state.story_content
    
    # Story content - use on_change callback and key parameter to ensure content is correctly saved
    st.text_area(
        "Create your science fiction story here... Your content will be automatically saved. After finishing, click the 'Submit' button", 
        height=200,
        value=st.session_state.story_content,
        placeholder="Create a science fiction story using your obtained vocabulary...",
        help="Each sentence must contain one of your obtained vocabulary words",
        key="temp_story_content",
        on_change=update_story_content
    )
    
    # Add automatic save prompt
    # if st.session_state.story_content:
    #     st.info("Your content will be automatically saved. Click the 'Sync to Database' button below to ensure content is permanently saved")

# Right sidebar - Purchased content
def render_right_sidebar():
    st.subheader("📖 Purchased")
    
    config = st.session_state.round_config
    if not config:
        st.error("Unable to get round configuration")
        return
    
    # Display owned vocabularies
    if st.session_state.owned_vocabs:
        st.markdown("#### 📝 Vocabulary")
        word_count = 0
        for vocab_id in st.session_state.owned_vocabs:
            vocab = next((v for v in config['vocabularies'] if v['id'] == vocab_id), None)
            if vocab:
                st.write(f"- {vocab['word']} (Price: ${vocab['price']:.2f})")
                word_count += 1
        st.markdown(f"Total owned words: {word_count}")
    else:
        st.info("No vocabulary selected yet")

# Main function
def main():
    init_session_state()
    
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
    st.markdown("### 📚 Story Templates")
    story_templates = [asset for asset in st.session_state.player_assets 
                        if asset.asset_type == 'story_template' and asset.content]
    
    if story_templates:
        for asset in story_templates:
            # Get story combo information
            combo = None
            for c in st.session_state.round_config.get('combinations', []):
                if set(json.loads(asset.used_vocabularies)) == set(c['vocab_ids']):
                    combo = c
                    break
            
            if combo:
                # Find corresponding story content
                story_data = next((s for s in combo['stories'] if s['content'] == asset.content), None)
                if story_data:
                    # Try to get rating from metadata
                    rating = ""
                    try:
                        metadata = json.loads(asset.asset_metadata) if asset.asset_metadata else {}
                        if 'rating' in metadata:
                            rating = f" (Rating: {metadata['rating']})"
                    except:
                        pass
                        
                    st.markdown(f"**Story{rating}**")
                    st.write(f"{asset.content}")
                    st.divider()
    else:
        st.info("No story templates purchased yet")
    
    # My Drafts section
    st.markdown("### 📝 My Drafts")
    story_drafts = [asset for asset in st.session_state.player_assets 
                    if asset.asset_type == 'story_draft' and asset.content]
    
    if story_drafts:
        # Sort by creation time
        sorted_drafts = sorted(story_drafts, key=lambda x: x.created_at, reverse=True)
        for asset in sorted_drafts[:1]:  # Only display the latest draft
            try:
                metadata = json.loads(asset.asset_metadata) if asset.asset_metadata else {}
                created_time = metadata.get('created_at', 'Unknown time')
                st.markdown(f"**Latest Draft (Saved: {created_time})**")
                st.write(f"{asset.content}")
                st.divider()
            except:
                pass
    else:
        st.info("No drafts saved yet")
    
    # My Creations section
    st.markdown("### 🖊️ My Creations")
    user_creations = [asset for asset in st.session_state.player_assets 
                        if asset.asset_type == 'user_creation' and asset.content]
    
    if user_creations:
        for asset in user_creations:
            st.markdown("**My Story**")
            st.write(f"{asset.content}")
            st.divider()
    else:
        st.info("No stories created yet")
    
    # Add automatic save feature
    # If there is content and it has been more than two minutes since last sync, automatically call sync function
    if 'story_content' in st.session_state and st.session_state.story_content:
        # Check last sync time
        current_time = datetime.now()
        if 'last_sync_time' not in st.session_state or (current_time - st.session_state.last_sync_time).total_seconds() > 120:
            # Use st.empty to display automatic save status
            auto_save_container = st.empty()
            success, _ = sync_to_database()
            if success:
                with auto_save_container:
                    st.info("✓ Content has been automatically saved")
            
            # Delay a few seconds before clearing message
            time.sleep(2)
            auto_save_container.empty()

if __name__ == "__main__":
    main()