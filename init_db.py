import os
from sqlalchemy import create_engine, text
import streamlit as st



# Database configuration
DATABASE_URL = f"mysql+pymysql://{st.secrets['DB_USER']}:{st.secrets['DB_PASSWORD']}@" \
               f"{st.secrets['DB_HOST']}:{st.secrets['DB_PORT']}/{st.secrets['DB_NAME']}"

# Create database engine
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=st.secrets['SQL_DEBUG'].lower() == 'true'
)

def init_database():
    """Initialize database table structure"""
    # SQL statements
    sql_statements = """
    -- Drop existing tables (if they exist)
    
    DROP TABLE IF EXISTS user_assets;
    DROP TABLE IF EXISTS players;
    DROP TABLE IF EXISTS game_rounds;

    -- Create players table
    CREATE TABLE players (
        player_id VARCHAR(30) PRIMARY KEY,  -- Format: a1 (a=round number, 1=participant number)
        total_earnings DECIMAL(10,2) UNSIGNED DEFAULT 0,
        current_round INT UNSIGNED DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP NULL,
        is_active BOOLEAN DEFAULT TRUE,
        INDEX idx_player_active (is_active)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    -- Create user assets table
    CREATE TABLE user_assets (
        asset_id VARCHAR(30) PRIMARY KEY,  -- Format: v1_a1_timestamp (v=vocabulary, s=story, u=user creation)
        player_id VARCHAR(30) NOT NULL,
        round_id INT UNSIGNED NOT NULL,  -- Round the asset belongs to
        asset_type VARCHAR(30) NOT NULL,
        content TEXT,  -- Can be empty for vocabulary type
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status ENUM('active', 'archived', 'submitted', 'approved', 'rejected') DEFAULT 'active',
        score INT,
        feedback TEXT,
        used_vocabularies JSON,  -- Store list of used vocabulary IDs
        asset_metadata JSON,  -- Metadata, can store price, IP rate, etc.
        FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE,
        INDEX idx_asset_type_status (asset_type, status, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    -- Create game rounds table
    CREATE TABLE game_rounds (
        round_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        round_number INT UNSIGNED NOT NULL UNIQUE,  -- Actual round number
        start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        end_time TIMESTAMP NULL,
        status ENUM('preparing', 'active', 'finished') DEFAULT 'preparing',
        parameters JSON,  -- Store vocabulary, combinations and story configurations for this round
        INDEX idx_round_status (status, start_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    -- Insert first round configuration
    INSERT INTO game_rounds (round_number, status, parameters) VALUES (
        1,
        'preparing',
        '{
            "round_number": 1,
            "vocabularies": [
                {
                    "id": "va1",
                    "word": "quantum",
                    "price": 10.00,
                    "category": "basic"
                },
                {
                    "id": "va2",
                    "word": "space-time",
                    "price": 10.00,
                    "category": "basic"
                },
                {
                    "id": "va3",
                    "word": "consciousness",
                    "price": 15.00,
                    "category": "premium"
                },
                {
                    "id": "va4",
                    "word": "matrix",
                    "price": 15.00,
                    "category": "premium"
                },
                {
                    "id": "va5",
                    "word": "virtual",
                    "price": 20.00,
                    "category": "premium"
                },
                {
                    "id": "va6",
                    "word": "reality",
                    "price": 20.00,
                    "category": "premium"
                },
                {
                    "id": "va7",
                    "word": "data",
                    "price": 25.00,
                    "category": "premium"
                },
                {
                    "id": "va8",
                    "word": "soul",
                    "price": 25.00,
                    "category": "premium"
                },
                {
                    "id": "va9",
                    "word": "consciousness matrix",
                    "price": 50.00,
                    "category": "rare"
                },
                {
                    "id": "va10",
                    "word": "quantum reality",
                    "price": 50.00,
                    "category": "rare"
                }
            ],
            "combinations": [
                {
                    "id": "ca1",
                    "owner": "system",
                    "vocab_ids": ["va1", "va2"],
                    "price": 20.00,
                    "stories": [
                        {
                            "id": "sa1",
                            
                            "content": "In the quantum realm, particles behave in mysterious ways. Space-time bends and twists around massive objects.",
                            "rating": 4.0,
                            "content_ip_rate": 1.5
                        },
                        {
                            "id": "sa2",
                            
                            "content": "2 - In the quantum realm, particles behave in mysterious ways. Space-time bends and twists around massive objects.",
                            "rating": 4.1,
                            "content_ip_rate": 1.6  
                        }
                    ]
                },
                {
                    "id": "ca2",
                    "owner": "system",
                    "vocab_ids": ["va3", "va4"],
                    "price": 30.00,
                    "stories": [
                        {
                            "id": "sa2",
                            
                            "content": "Human consciousness remains one of the greatest mysteries of science. The matrix of reality is woven from the fabric of our perceptions.",
                            "rating": 4.2,
                            "content_ip_rate": 1.6
                        }
                    ]
                },
                {
                    "id": "ca3",
                    "owner": "system",
                    "vocab_ids": ["va5", "va6"],
                    "price": 40.00,
                    "stories": [
                        {
                            "id": "sa3",
                            
                            "content": "The virtual world offers endless possibilities for exploration. Reality becomes fluid when we step into the digital realm.",
                            "rating": 4.3,
                            "content_ip_rate": 1.7
                        }
                    ]
                },
                {
                    "id": "ca4",
                    "owner": "system",
                    "vocab_ids": ["va7", "va8"],
                    "price": 50.00,
                    "stories": [
                        {
                            "id": "sa4",
                            
                            "content": "Data flows like rivers through the digital landscape. The soul finds new ways to express itself in the age of technology.",
                            "rating": 4.5,
                            "content_ip_rate": 1.8
                        }
                    ]
                },
                {
                    "id": "ca5",
                    "owner": "system",
                    "vocab_ids": ["va9", "va10"],
                    "price": 100.00,
                    "stories": [
                        {
                            "id": "sa5",
                            
                            "content": "The quantum consciousness reveals the interconnectedness of all things. The matrix of existence is woven from the threads of probability.",
                            "rating": 5.0,
                            "content_ip_rate": 2.0
                        }
                    ]
                }
            ],
            "initial_balance": 100.00
        }'
    );
    """

    try:
        # Execute SQL statements
        with engine.connect() as connection:
            # Split SQL statements and execute them one by one
            for statement in sql_statements.split(';'):
                if statement.strip():
                    connection.execute(text(statement))
            connection.commit()
        print("Database initialization successful!")
    except Exception as e:
        print(f"Database initialization failed: {str(e)}")
        raise

if __name__ == "__main__":
    init_database() 