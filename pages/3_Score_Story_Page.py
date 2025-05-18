import streamlit as st
import pandas as pd
from models import UserAsset, StoryRating
from service import StoryRatingService, UserAssetService
from config import get_db
import random
import time

# Set page configuration
st.set_page_config(layout="wide", page_title="Story Rating Page", page_icon="⭐")

# Initialize session state
def init_session_state():
    # Check if logged in
    if 'player_id' not in st.session_state or st.session_state.player_id == "":
        st.switch_page("pages/1_Instructions_Page.py")
        return
    
    # If already initialized, no need to execute again
    if 'stories_for_rating' in st.session_state:
        return
    
    db = next(get_db())
    try:
        # 1. Get all stories for rating in the current round
        stories = db.query(UserAsset).filter(
            UserAsset.round_id == st.secrets['round_id'],
            UserAsset.asset_type == 'user_creation'
        ).order_by(UserAsset.created_at.desc()).all()
        
        # 2. Get the story IDs the user has already rated
        user_ratings = StoryRatingService.get_player_ratings(db, st.session_state.player_id)
        rated_story_ids = {rating.asset_id for rating in user_ratings}
        
        # 3. Filter out stories the user hasn't rated yet
        st.session_state.stories_for_rating = []
        for story in stories:
            # If the user hasn't rated this story yet
            if story.asset_id not in rated_story_ids:
                # Record the original IP rate
                story.original_ip_rate = story.content_ip_rate
                st.session_state.stories_for_rating.append(story)
                
        # Initialize rating data in session state
        if 'rating_data' not in st.session_state:
            st.session_state.rating_data = {}
            for i, story in enumerate(st.session_state.stories_for_rating):
                st.session_state.rating_data[story.asset_id] = {
                    'creativity': 4,
                    'coherence': 4,
                    'overall': 4,
                    'original_ip_rate': story.original_ip_rate
                }
    finally:
        db.close()

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
                    if f"creativity_{i}" in st.session_state:
                        st.session_state.rating_data[asset_id]['creativity'] = st.session_state[f"creativity_{i}"]
                    if f"coherence_{i}" in st.session_state:
                        st.session_state.rating_data[asset_id]['coherence'] = st.session_state[f"coherence_{i}"]
                    if f"overall_{i}" in st.session_state:
                        st.session_state.rating_data[asset_id]['overall'] = st.session_state[f"overall_{i}"]
            
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
    
    # Display stories for rating
    if 'stories_for_rating' not in st.session_state or not st.session_state.stories_for_rating:
        st.success("You have rated all available stories. Thank you!")
        return
    
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
                
                # Creativity rating
                creativity = st.slider(
                    "Creativity", 
                    min_value=1, 
                    max_value=7, 
                    value=st.session_state.rating_data[story.asset_id]['creativity'],
                    help="New ideas, original concepts, and innovative elements in the story",
                    key=f"creativity_{i}"
                )
                
                # Coherence rating
                coherence = st.slider(
                    "Coherence", 
                    min_value=1, 
                    max_value=7, 
                    value=st.session_state.rating_data[story.asset_id]['coherence'],
                    help="Structure, logic, and coherence of the story",
                    key=f"coherence_{i}"
                )
                
                # Overall rating
                overall = st.slider(
                    "Overall", 
                    min_value=1, 
                    max_value=7, 
                    value=st.session_state.rating_data[story.asset_id]['overall'],
                    help="Overall quality of the story considering all aspects",
                    key=f"overall_{i}"
                )
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
                    
                    # Creativity rating
                    creativity = st.slider(
                        "Creativity", 
                        min_value=1, 
                        max_value=7, 
                        value=st.session_state.rating_data[story.asset_id]['creativity'],
                        help="New ideas, original concepts, and innovative elements in the story",
                        key=f"creativity_{i+1}"
                    )
                    
                    # Coherence rating
                    coherence = st.slider(
                        "Coherence", 
                        min_value=1, 
                        max_value=7, 
                        value=st.session_state.rating_data[story.asset_id]['coherence'],
                        help="Structure, logic, and coherence of the story",
                        key=f"coherence_{i+1}"
                    )
                    
                    # Overall rating
                    overall = st.slider(
                        "Overall", 
                        min_value=1, 
                        max_value=7, 
                        value=st.session_state.rating_data[story.asset_id]['overall'],
                        help="Overall quality of the story considering all aspects",
                        key=f"overall_{i+1}"
                    )
                    st.divider()
        
        # Single submit button at the bottom for all ratings
        submit_button = st.form_submit_button("Submit All Ratings", type="primary", use_container_width=True)
        
        if submit_button:
            # Submit all ratings
            success, message = submit_all_ratings()
            
            if success:
                st.success(message)
                # Refresh page, remove rated stories
                st.session_state.stories_for_rating = None
                st.session_state.rating_data = None
                st.experimental_rerun()
            else:
                st.error(message)

if __name__ == "__main__":
    main()
