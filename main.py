import streamlit as st
# Sidebar navigation
st.sidebar.title("Navigation")
page_selection = st.sidebar.radio("Go to", ["Instructions", "Experiment", "Rate Stories"], key='page')
if page_selection == "Instructions":          st.switch_page("pages/1_Instructions_Page.py")
elif page_selection == "Experiment":
    if st.session_state.comp_check_passed:    st.switch_page("pages/2_Experiment_Page.py")
    else: st.warning("Please complete the instructions first")
elif page_selection == "Rate Stories":
    if st.session_state.comp_check_passed:    st.switch_page("pages/3_Score_Story_Page.py")
    else: st.warning("Please complete the instructions first")
# Set page configuration
# st.set_page_config(
#     page_title="Sci-Fi Novel Creation",
#     page_icon="📚",
#     layout="wide"
# )

# # Initialize session state
# if 'player_id' not in st.session_state:
#     st.session_state.player_id = "test"  # Use string type player_id
# if 'comp_check_passed' not in st.session_state:
#     st.session_state.comp_check_passed = True

# # Switch to experiment page directly
# st.switch_page("pages/2_Experiment_Page.py")
