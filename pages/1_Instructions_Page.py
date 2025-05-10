import streamlit as st

def main():
    # if 'player_id' not in st.session_state:
    #     st.session_state.player_id = 'text4'  # Use integer type player_id
    # if 'comp_check_passed' not in st.session_state:
    #     st.session_state.comp_check_passed = True
    # st.switch_page("pages/2_Experiment_Page.py")

    # Initialize session state
    if 'comp_check_passed' not in st.session_state:
        st.session_state.comp_check_passed = False
        st.session_state.attempts = 0
        st.session_state.player_id = ""

    # Header
    st.title("Story Creation Experiment")
    st.write("Thank you for participating in this research about Story Creation and Sequential Innovation.")

    # Study information expander
    with st.expander("📋 Study Instructions", expanded=True):
        st.markdown("""
        ### What You Need to Do:
        1. **Purchase** words / word combinations / story content to create stories
        2. **Create** a science fiction short story based on whar you purchased
        3. **Submit** your work, set copyright transfer fees and submit
        
        ### After You Submit:
        1. Your work will be scored by an independent jury based on the overall impression
        2. The word combination you used and your work's score will be displayed in the "Story Square" for the next round of participants
        3. Next round participants can purchase your word combination at word prices, or buy your complete work at your set copyright transfer fee
        4. If your work / word combination are purchased, you will receive additional compensation; otherwise you will only receive the base compensation

        ### Important Rules:
         - When creating, ensure each sentence contains exactly one of your chosen words (one word per sentence)
         - A word can only be used once
         - Please do not close the browser or skip questions during the experiment
         - If you encounter technical issues, please refresh the page to restart
         - You can withdraw from the study at any time without penalty

        """)

    # Comprehension check (only show if not passed)
    if not st.session_state.comp_check_passed:
        st.divider()
        st.subheader("Before You Begin...")
        st.write("Please answer the following question to continue:")

        prolific_id = st.text_input("Please enter your unique Prolific ID, then press Enter to confirm:", 
                               value=st.session_state.player_id)
            

        answer = st.radio(
            "When creating a story, what should each sentence contain?",
            options=[
                "No specific content required",
                "Must contain one of your chosen words",
                "Must contain all of your chosen words"
            ],
            index=None
        )

        if st.button("Submit Answer"):
            if answer == "Must contain one of your chosen words":
                if st.session_state.attempts >= 2:
                    st.warning('You have failed to pass the Comprehension Check too many times. Thank you for your time. Please close the browser and return to Prolific.')
                    #st.warning("Your redeem code is: EFTR-9M3E-0I6T")
                    st.stop()

                if prolific_id:
                    st.session_state.player_id = prolific_id
                    st.session_state.comp_check_passed = True
                    st.success("✓ Correct! You may now begin the study.")
                    st.balloons()
                else:
                    st.warning("Please enter your Prolific ID to continue.")
                    #st.snow()
                #st.snow()
            else:
                st.session_state.attempts += 1
                if st.session_state.attempts >= 2:
                    st.warning('You have failed to pass the Comprehension Check too many times. Thank you for your time. Please close the browser and return to Prolific.')
                    st.stop()
                else:
                    st.warning("Incorrect answer. Please review the instructions and try again.")

    # Continue button (only shows after passing)
    if st.session_state.comp_check_passed:
        st.divider()
        if st.button("Let's Go!", type="primary"):
            st.switch_page("pages/2_Experiment_Page.py")

if __name__ == "__main__":
    main()