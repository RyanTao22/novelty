import streamlit as st
import pandas as pd
from models import UserAsset, StoryRating
from service import StoryRatingService, UserAssetService
from config import get_db
import random
import time

# Set page configuration
st.set_page_config(layout="wide", page_title="Story Rating Page", page_icon="⭐")

# 定义评分项配置
RATING_CONFIGS = {
    'creativity': {
        'label': "Creativity",
        'help': "New ideas, original concepts, and innovative elements in the story",
        'min_value': 1,
        'max_value': 7,
        'default_value': 1
    },
    'coherence': {
        'label': "Coherence",
        'help': "Structure, logic, and coherence of the story",
        'min_value': 1,
        'max_value': 7,
        'default_value': 1
    },
    'overall': {
        'label': "Overall",
        'help': "Overall quality of the story considering all aspects",
        'min_value': 1,
        'max_value': 7,
        'default_value': 1
    }
}

# Initialize session state
def init_session_state():
    # Check if logged in
    if 'player_id' not in st.session_state or st.session_state.player_id == "":
        st.switch_page("pages/1_Instructions_Page.py")
        return
    
    # If already initialized, no need to execute again
    if 'stories_for_rating' in st.session_state:
        return
    
    # 显示加载提示
    loading_placeholder = st.empty()
    loading_placeholder.info("DEBUG: Loading rating data...")
    
    db = next(get_db())
    try:
        # 1. Get all stories for rating in the current round
        loading_placeholder.info("DEBUG: Querying stories...")
        stories = db.query(UserAsset).filter(
            UserAsset.round_id == st.secrets['round_id'],
            UserAsset.asset_type == 'user_creation'
        ).order_by(UserAsset.created_at.desc()).all()
        
        # 2. Get the story IDs the user has already rated
        loading_placeholder.info("DEBUG: Getting rated stories...")
        user_ratings = StoryRatingService.get_player_ratings(db, st.session_state.player_id)
        rated_story_ids = {rating.asset_id for rating in user_ratings}
        
        # 3. Filter out stories the user hasn't rated yet
        loading_placeholder.info("DEBUG: Filtering unrated stories...")
        st.session_state.stories_for_rating = []
        for story in stories:
            # If the user hasn't rated this story yet
            if story.asset_id not in rated_story_ids:
                # Record the original IP rate
                story.original_ip_rate = story.content_ip_rate
                st.session_state.stories_for_rating.append(story)
                
        # Initialize rating data in session state
        loading_placeholder.info("DEBUG: Initializing rating data...")
        if 'rating_data' not in st.session_state:
            st.session_state.rating_data = {}
            for i, story in enumerate(st.session_state.stories_for_rating):
                st.session_state.rating_data[story.asset_id] = {
                    rating_type: config['default_value'] 
                    for rating_type, config in RATING_CONFIGS.items()
                }
                st.session_state.rating_data[story.asset_id]['original_ip_rate'] = story.original_ip_rate
        
        # 清除加载提示
        loading_placeholder.empty()
    finally:
        db.close()

# 生成评分滑块的函数
def create_rating_sliders(story, index):
    
    ratings = {}
    
    for rating_type, config in RATING_CONFIGS.items():
        ratings[rating_type] = st.slider(
            config['label'],
            min_value=config['min_value'],
            max_value=config['max_value'],
            value=st.session_state.rating_data[story.asset_id][rating_type],
            help=config['help'],
            key=f"{rating_type}_{index}"
        )
    
    return ratings

# Submit all ratings function
def submit_all_ratings():
    db = next(get_db())
    success_count = 0
    total_count = len(st.session_state.rating_data)
    
    try:
        for asset_id, ratings in st.session_state.rating_data.items():
            # Update rating values from session state before submission
            for i, story in enumerate(st.session_state.stories_for_rating):
                if story.asset_id == asset_id:
                    # Check if the keys exist in session state and update
                    for rating_type in RATING_CONFIGS.keys():
                        key = f"{rating_type}_{i}"
                        if key in st.session_state:
                            st.session_state.rating_data[asset_id][rating_type] = st.session_state[key]
            
            # Use fixed IP rate value 2.0 as the rater's IP rate setting
            rating = StoryRatingService.create_rating(
                db,
                st.session_state.player_id,
                asset_id,
                st.session_state.rating_data[asset_id]['creativity'],
                st.session_state.rating_data[asset_id]['coherence'],
                st.session_state.rating_data[asset_id]['overall'],
                content_ip_rate=2.0,  # Fixed value, no need for user to set
                comment="",  # No comments as per requirement
                original_ip_rate=ratings['original_ip_rate']
            )
            
            if rating:
                success_count += 1
        
        if success_count == total_count:
            return True, "All ratings submitted successfully"
        else:
            return False, f"Only {success_count} out of {total_count} ratings were submitted successfully"
    finally:
        db.close()

def main():
    # Initialize session state
    init_session_state()
    
    # Page title
    st.title("Story Rating System")
    
    # 添加一个状态标记，判断是否已完成评分
    if 'rating_completed' not in st.session_state:
        st.session_state.rating_completed = False
    
    # 如果已完成评分，只显示完成信息
    if st.session_state.rating_completed:
        st.success('Study completed successfully! Please click the link below to return to Prolific and finalize your submission, then close this browser.')
        st.success(f"Completion URL: {st.secrets['completion_url']}")
        st.balloons()
        return
    
    # Display stories for rating
    if 'stories_for_rating' not in st.session_state or not st.session_state.stories_for_rating:
        st.success("You have rated all available stories. Thank you!")
        # 标记评分已完成
        st.session_state.rating_completed = True
        st.rerun()
        return
    
    # 以下是评分表单部分
    # Grid layout for stories (2 stories per row)
    stories = st.session_state.stories_for_rating
    num_stories = len(stories)
    
    with st.form(key="all_ratings_form"):
        for i in range(0, num_stories, 2):
            # Create a row with 2 columns
            cols = st.columns(2)
            
            # Left column: first story in the pair
            with cols[0]:
                story = stories[i]
                st.subheader(f"Story {i+1}")
                
                # Upper half: Story content
                st.markdown("**Story Content:**")
                st.write(story.content)
                
                # Lower half: Rating controls
                st.markdown("**Rating (1-7)**")
                
                # 使用函数生成评分滑块
                create_rating_sliders(story, i)
                st.divider()
            
            # Right column: second story in the pair (if available)
            if i + 1 < num_stories:
                with cols[1]:
                    story = stories[i+1]
                    st.subheader(f"Story {i+2}")
                    
                    # Upper half: Story content
                    st.markdown("**Story Content:**")
                    st.write(story.content)
                    
                    # Lower half: Rating controls
                    st.markdown("**Rating (1-7)**")
                    
                    # 使用函数生成评分滑块
                    create_rating_sliders(story, i+1)
                    st.divider()
        
        # Single submit button at the bottom for all ratings
        submit_button = st.form_submit_button("Submit All Ratings", type="primary", use_container_width=True)
        
        if submit_button:
            # Submit all ratings
            success, message = submit_all_ratings()
            
            if success:
                # 标记评分已完成
                st.session_state.rating_completed = True
                st.rerun()
            else:
                st.error(message)

if __name__ == "__main__":
    main()
