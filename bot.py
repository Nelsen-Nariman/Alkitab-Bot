from dotenv import load_dotenv
import os
import discord
from discord import app_commands
from discord.ext import commands
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from datetime import datetime
from pytz import timezone
import pytz
import sqlite3
import aiohttp
from aiohttp import web
import asyncio

# Short and full book name mapping
book_mapping = {
    "Kej": "Kejadian", "Kel": "Keluaran", "Ima": "Imamat", "Bil": "Bilangan", "Ula": "Ulangan",
    "Yos": "Yosua", "Hak": "Hakim-hakim", "Rut": "Rut", "1Sa": "1 Samuel", "2Sa": "2 Samuel",
    "1Ra": "1 Raja-raja", "2Ra": "2 Raja-raja", "1Ta": "1 Tawarikh", "2Ta": "2 Tawarikh",
    "Ezr": "Ezra", "Neh": "Nehemia", "Est": "Ester", "Ayb": "Ayub", "Mzm": "Mazmur",
    "Ams": "Amsal", "Pkh": "Pengkhotbah", "Kid": "Kidung Agung", "Yes": "Yesaya",
    "Yer": "Yeremia", "Rat": "Ratapan", "Yeh": "Yehezkiel", "Dan": "Daniel", "Hos": "Hosea",
    "Yoe": "Yoel", "Amo": "Amos", "Oba": "Obaja", "Yun": "Yunus", "Mik": "Mikha",
    "Nah": "Nahum", "Hab": "Habakuk", "Zef": "Zefanya", "Hag": "Hagai", "Zak": "Zakharia",
    "Mal": "Maleakhi", "Mat": "Matius", "Mrk": "Markus", "Luk": "Lukas", "Yoh": "Yohanes",
    "Kis": "Kisah Para Rasul", "Rom": "Roma", "1Ko": "1 Korintus", "2Ko": "2 Korintus",
    "Gal": "Galatia", "Efe": "Efesus", "Flp": "Filipi", "Kol": "Kolose", "1Te": "1 Tesalonika",
    "2Te": "2 Tesalonika", "1Ti": "1 Timotius", "2Ti": "2 Timotius", "Tit": "Titus",
    "Flm": "Filemon", "Ibr": "Ibrani", "Yak": "Yakobus", "1Pt": "1 Petrus", "2Pt": "2 Petrus",
    "1Yo": "1 Yohanes", "2Yo": "2 Yohanes", "3Yo": "3 Yohanes", "Yud": "Yudas", "Why": "Wahyu"
}

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Set up bot
intents = discord.Intents.default()
intents.message_content = True  # Ensure bot can read messages' content
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Set Asia/Jakarta timezone
jakarta_tz = timezone("Asia/Jakarta")

# Scheduler
scheduler = AsyncIOScheduler()

@bot.event
async def on_ready():
    init_database()
    print(f'{bot.user} is now online!')

    # Configure scheduler with Jakarta timezone
    jobstores = {
        'default': MemoryJobStore()
    }
    job_defaults = {
        'coalesce': False,
        'max_instances': 3
    }

    try:
        # Sync commands only once, globally
        await bot.tree.sync()
        print("Commands synced globally")
        
        scheduler.configure(jobstores=jobstores, job_defaults=job_defaults, timezone=jakarta_tz)
        scheduler.start()

        # Start HTTP server
        http_app = create_http_server()
        runner = web.AppRunner(http_app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8000)
        await site.start()
        print("HTTP Server started on http://localhost:8000")

    except Exception as e:
        print(f"Error during startup: {e}")
    

# Helper function to find the target channel
async def get_target_channel(ctx, channel_name):
    target_channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
    if not target_channel:
        await ctx.send(f"Channel #{channel_name} not found. Please create it.")
    return target_channel

# Function to generate the URL and full name for a given Bible verse
def generate_bible_hyperlink(verse):
    base_url = "https://alkitab.mobi/tb"

    # Create a reverse mapping to find the short name from the full name
    reverse_mapping = {v: k for k, v in book_mapping.items()}

    # Split the verse into short_name and remaining
    last_space_index = verse.rfind(" ")
    if last_space_index != -1:
        short_name = verse[:last_space_index]  # Everything before the last space
        remaining = verse[last_space_index + 1:]  # Everything after the last space
    else:
        short_name = verse
        remaining = ""

    # Replace abbreviation with the full name
    full_name = book_mapping.get(short_name, short_name)

    # Find the short name for the full name in the reverse mapping
    short_name_for_url = reverse_mapping.get(full_name, full_name)

    # Construct the formatted_verse using the short name
    formatted_verse = f"{short_name_for_url} {remaining}".strip()

    # Format the URL
    if ":" in formatted_verse and "-" in formatted_verse:
        url = f"{base_url}/passage/{formatted_verse.replace(' ', '+').replace(':', ':').replace('-', '-')}"
    elif ":" in formatted_verse:
        url = f"{base_url}/{formatted_verse.replace(' ', '/').replace(':', '/')}"
    else:
        url = f"{base_url}/{formatted_verse.replace(' ', '/')}"

    # Replace spaces in book names for display
    display_name = full_name + (" " + remaining if remaining else "")
    return f"[{display_name}]({url})"

# HTTP Server Route Handlers
async def health_check(request):
    """Simple health check endpoint"""
    return web.Response(text="Bible Bot is running!", status=200)

async def get_reading_reports(request):
    """Endpoint to retrieve reading reports"""
    conn = sqlite3.connect('reading_tracker.db')
    try:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT 
            ReadingReport_ID, 
            Date, 
            Bible_Verse, 
            Usernames,
            (LENGTH(Usernames) - LENGTH(REPLACE(Usernames, ',', '')) + 1) AS Total_Read
        FROM reading_reports
        ''')
        
        reports = cursor.fetchall()
        
        # Convert to list of dictionaries
        column_names = [
            'ReadingReport_ID', 
            'Date', 
            'Bible_Verse', 
            'Usernames', 
            'Total_Read'
        ]
        
        reports_list = [dict(zip(column_names, report)) for report in reports]
        
        return web.json_response(reports_list)
    except sqlite3.Error as e:
        return web.json_response({"error": str(e)}, status=500)
    finally:
        conn.close()

async def start_background_tasks(app):
    """Start background tasks when the app starts"""
    # You can add any additional background tasks here if needed
    pass

async def cleanup_background_tasks(app):
    """Cleanup background tasks when the app shuts down"""
    # Add any cleanup logic if necessary
    pass

def create_http_server():
    """Create and configure the HTTP server"""
    app = web.Application()
    
    # Add routes
    app.router.add_get('/', health_check)
    app.router.add_get('/reports', get_reading_reports)
    
    # Add lifecycle hooks
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    return app
    
# SQLite Database for Tracking
def init_database():
    conn = sqlite3.connect('reading_tracker.db')
    cursor = conn.cursor()
    
    # Drop the table if it exists to ensure fresh creation
    cursor.execute('DROP TABLE IF EXISTS reading_reports')
    
    # Create tables with new columns
    cursor.execute('''
    CREATE TABLE reading_reports (
        ReadingReport_ID INTEGER PRIMARY KEY AUTOINCREMENT,
        ReadingPlan_ID INTEGER,
        Usernames TEXT DEFAULT '',
        Date TEXT DEFAULT '',
        Bible_Verse TEXT DEFAULT ''
    )
    ''')
    
    conn.commit()
    conn.close()

def save_reading_report(reading_plan_id, username, date=None, bible_verse=None):
    conn = sqlite3.connect('reading_tracker.db')
    cursor = conn.cursor()
    
    try:
        # Check if this specific user has already reported for this reading plan
        cursor.execute('''
        SELECT * FROM reading_reports 
        WHERE ReadingPlan_ID = ? AND Usernames LIKE ?
        ''', (reading_plan_id, f'%{username}%'))
        
        existing_report = cursor.fetchone()
        
        if existing_report:
            # User has already reported
            conn.close()
            return False
        
        # If no existing report for this user and reading plan, proceed to save
        cursor.execute('''
        SELECT * FROM reading_reports 
        WHERE ReadingPlan_ID = ?
        ''', (reading_plan_id,))
        
        existing_general_report = cursor.fetchone()
        
        if existing_general_report:
            # If report exists, update Usernames
            report_id = existing_general_report[0]
            current_usernames = existing_general_report[2] or ''
            
            # Add new username
            usernames_list = current_usernames.split(', ') if current_usernames else []
            usernames_list.append(username)
            
            updated_usernames = ', '.join(usernames_list)
            
            cursor.execute('''
            UPDATE reading_reports 
            SET Usernames = ?, Date = ?, Bible_Verse = ?
            WHERE ReadingReport_ID = ?
            ''', (updated_usernames, date, bible_verse, report_id))
        else:
            # If no report exists, create a new one
            cursor.execute('''
            INSERT INTO reading_reports (ReadingPlan_ID, Usernames, Date, Bible_Verse) 
            VALUES (?, ?, ?, ?)
            ''', (reading_plan_id, username, date, bible_verse))
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def validate_reading_plan_data(data, book_mapping):
    """
    Validate the imported reading plan data with comprehensive checks.
    
    Args:
        data (pd.DataFrame): The imported DataFrame
        book_mapping (dict): Dictionary of valid book abbreviations
    
    Returns:
        tuple: (is_valid, error_messages)
    """
    error_messages = []
    invalid_verses_list = []  # New list to track specific invalid verses

    # Comprehensive column checks
    required_columns = ['ReadingPlan_ID', 'Date', 'Time', 'Bible_Verse']
    # Comprehensive column checks
    missing_columns = [column for column in required_columns if column not in data.columns]
    if missing_columns:
        error_messages.extend([f"❌ Missing '{column}' column" for column in missing_columns])
        return False, error_messages

    # Check 1: ReadingPlan_ID validation
    # Empty value check
    empty_ids = data[data['ReadingPlan_ID'].isna()]
    if not empty_ids.empty:
        error_messages.append("❌ ReadingPlan_ID column cannot have empty values")

    # Type validation
    try:
        data['ReadingPlan_ID'] = data['ReadingPlan_ID'].astype(int)
    except (ValueError, TypeError):
        error_messages.append("❌ ReadingPlan_ID must be an integer")

    # Duplicate value check
    duplicate_ids = data[data.duplicated(subset=['ReadingPlan_ID'], keep=False)]
    if not duplicate_ids.empty:
        duplicate_values = duplicate_ids['ReadingPlan_ID'].unique()
        error_messages.append("❌ ReadingPlan_ID must be unique. Duplicate values found.")
        error_messages.append(f"    Duplicate IDs: {duplicate_values}")

    # Check 2: Date validation
    empty_dates = data[data['Date'].isna()]
    if not empty_dates.empty:
        error_messages.append("❌ Date column cannot have empty values")

    # Check 3: Time validation
    empty_times = data[data['Time'].isna()]
    if not empty_times.empty:
        error_messages.append("❌ Time column cannot have empty values")

    # Check 4: Bible Verse validation
    empty_verses = data[data['Bible_Verse'].isna()]
    if not empty_verses.empty:
        error_messages.append("❌ Bible_Verse column cannot have empty values")

    # Date format validation
    def is_valid_date(date_str):
        date_formats = [
            "%Y-%m-%d",      # YYYY-MM-DD
            "%m/%d/%Y",      # MM/DD/YYYY
            "%d-%b-%y",      # DD-Mon-YY
            "%Y-%m-%d %H:%M:%S"  # YYYY-MM-DD with time
        ]
        
        for fmt in date_formats:
            try:
                datetime.strptime(str(date_str), fmt)
                return True
            except ValueError:
                continue
        return False

    invalid_dates = data[~data['Date'].apply(is_valid_date)]
    if not invalid_dates.empty:
        if empty_dates.empty:
            error_messages.append("❌ Invalid date format")
            error_messages.append("    Valid formats: 'YYYY-MM-DD', 'MM/DD/YYYY', 'DD-Mon-YY'")

    # Time format validation
    def is_valid_time(time_str):
        time_formats = [
            "%H:%M",      # 24-hour format
            "%H:%M:%S",   # 24-hour format with seconds
            "%I:%M %p"    # 12-hour format with AM/PM
        ]
        
        for fmt in time_formats:
            try:
                datetime.strptime(str(time_str), fmt)
                return True
            except ValueError:
                continue
        return False

    invalid_times = data[~data['Time'].apply(is_valid_time)]
    if not invalid_times.empty:
        if empty_times.empty:
            error_messages.append("❌ Invalid time format")
            error_messages.append("    Valid formats: '14:30', '14:30:00', '2:30 PM'")

    # Bible verse validation with detailed tracking
    def validate_bible_verse(verse_str):
        # Create a reverse mapping (long name to short name)
        reverse_mapping = {v: k for k, v in book_mapping.items()}
        
        # Combine both mappings for validation
        combined_mapping = {**book_mapping, **reverse_mapping}
        
        # Split multiple verses
        verses = [v.strip() for v in str(verse_str).split(",")]
        
        # Track invalid verses for this specific verse_str
        invalid_verses_for_entry = []
        
        for verse in verses:
            # Extract the book name (part before the last space)
            last_space_index = verse.rfind(" ")
            if last_space_index != -1:
                book_name = verse[:last_space_index]
            else:
                book_name = verse
            
            # Validate against the combined mapping
            if book_name not in combined_mapping:
                invalid_verses_for_entry.append(verse)
        
        return len(invalid_verses_for_entry) == 0, invalid_verses_for_entry

    # Track invalid entries with their specific problematic verses
    invalid_verse_entries = []
    for index, row in data.iterrows():
        is_valid, invalid_verses = validate_bible_verse(row['Bible_Verse'])
        if not is_valid:
            invalid_verse_entries.append({
                'row': index + 1,  # Excel-like row numbering (add 2 to account for header)
                'verse': row['Bible_Verse'],
                'invalid_parts': invalid_verses
            })

    if invalid_verse_entries:
        if empty_verses.empty:
            error_messages.append("❌ Invalid Bible verse abbreviations")
            
            # Detailed error reporting
            for entry in invalid_verse_entries:
                error_messages.append(f"    At Row {entry['row']}: '{entry['verse']}'")
            
            error_messages.append("    Ensure all book abbreviations are valid (e.g., '1Ko 13', '1Ko 3:16', '1 Korintus 5:3-7')")

    # Determine overall validation status
    is_valid = len(error_messages) == 0

    return is_valid, error_messages


# Export reading reports to Excel
@bot.tree.command(name="export_data")
async def export_reading_reports(interaction: discord.Interaction):
    await interaction.response.defer()
    
    conn = sqlite3.connect('reading_tracker.db')
    
    try:
        # First, we need to modify the database to store the original scheduling information
        cursor = conn.cursor()
        cursor.execute('''
        ALTER TABLE reading_reports 
        ADD COLUMN Date TEXT DEFAULT '';
        ''')
        
        cursor.execute('''
        ALTER TABLE reading_reports 
        ADD COLUMN Bible_Verse TEXT DEFAULT '';
        ''')
        
        conn.commit()

        # Read data into pandas DataFrame
        df = pd.read_sql_query('''
        SELECT 
            ReadingReport_ID, 
            Date, 
            Bible_Verse, 
            Usernames,
            (LENGTH(Usernames) - LENGTH(REPLACE(Usernames, ',', '')) + 1) AS Total_Read
        FROM reading_reports
        ''', conn)
        
        # Rename columns for clarity
        df.columns = [
            'ReadingReport_ID', 
            'Date', 
            'Bible_Verse', 
            'Usernames', 
            'Total_Read'
        ]
        
        # Convert Date column to datetime and format it
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df['Date'] = df['Date'].dt.strftime('%d-%b-%y')
        
        # Export to Excel
        filename = 'Reading_Reports.xlsx'
        df.to_excel(filename, index=False)
        
        # Send the file
        await interaction.followup.send(
            "Here are the reading reports:", 
            file=discord.File(filename)
        )
    except sqlite3.OperationalError as e:
        # If columns already exist, just proceed with the query
        if "duplicate column name" in str(e).lower():
            df = pd.read_sql_query('''
            SELECT 
                ReadingReport_ID, 
                Date, 
                Bible_Verse, 
                Usernames,
                (LENGTH(Usernames) - LENGTH(REPLACE(Usernames, ',', '')) + 1) AS Total_Read
            FROM reading_reports
            ''', conn)
            
            # Rename columns for clarity
            df.columns = [
                'ReadingReport_ID', 
                'Date', 
                'Bible_Verse', 
                'Usernames', 
                'Total_Read'
            ]
            
            # Convert Date column to datetime and format it
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            df['Date'] = df['Date'].dt.strftime('%d-%b-%y')
            
            # Export to Excel
            filename = 'Reading_Reports.xlsx'
            df.to_excel(filename, index=False)
            
            # Send the file
            await interaction.followup.send(
                "Here are the reading reports:", 
                file=discord.File(filename)
            )
        else:
            await interaction.followup.send(f"Error exporting data: {e}")
    except Exception as e:
        await interaction.followup.send(f"Error exporting data: {e}")
    finally:
        conn.close()

# Command to import spreadsheet with file attachment
@bot.tree.command(name="import_schedule")
@app_commands.describe(
    channel_name="Which channel you want to send messages to?",
    file="Upload your Excel file with the reading plan."
)
async def import_schedule(interaction: discord.Interaction, channel_name: str, file: discord.Attachment):
    print("Received import_schedule command")

    # Defer the response to handle longer processing times
    await interaction.response.defer()

    if not file.filename.endswith(('.xlsx', '.xls')):
        await interaction.followup.send("❌ Please upload a valid Excel file (.xlsx or .xls).")
        return

    file_path = f"./{file.filename}"

    # Save the uploaded file locally
    await file.save(file_path)

    try:
        # Load the Excel file without strict dtype for ReadingPlan_ID
        data = pd.read_excel(file_path)
        
        # Ensure correct column names
        # data.columns = ['ReadingPlan_ID', 'Date', 'Time', 'Bible_Verse'][:len(data.columns)]
        
        # Validate for empty and invalid values in ReadingPlan_ID
        if 'ReadingPlan_ID' not in data.columns or data['ReadingPlan_ID'].isna().any():
            await interaction.followup.send("❌ ReadingPlan_ID column cannot be empty.")
            return
        
        # Attempt to cast ReadingPlan_ID to int, handling errors gracefully
        try:
            data['ReadingPlan_ID'] = data['ReadingPlan_ID'].astype(int)
        except ValueError:
            await interaction.followup.send("❌ ReadingPlan_ID column must be numbers. For example: 1")
            return

        # Validate the imported data against the book mapping
        is_valid, validation_messages = validate_reading_plan_data(data, book_mapping)

        # If validation fails, send detailed error messages
        if not is_valid:
            error_message = "\n".join(validation_messages)
            
            # Optional: Provide an example of a correct Excel format
            example_message = """
    📝 Example of a Correct Excel Format:
    ReadingPlan_ID = 1
    Date = 2024-01-15
    Time = 07:00
    Bible_Verse = 1 Korintus 5:3-7
            """
            
            await interaction.followup.send(f"{error_message}\n\n{example_message}")
            return

        print("Columns:", list(data.columns))
        print("Data types:", data.dtypes)
        print("\nFirst few rows:")
        print(data.head())

    except Exception as e:
        print(f"Error reading file: {e}")
        await interaction.followup.send(f"Error reading file: {e}")
        return


    # Get the target channel
    target_channel = await get_target_channel(interaction, channel_name)
    if not target_channel:
        return
    
    # Remove existing schedules for the imported IDs
    existing_jobs = scheduler.get_jobs()
    imported_ids = data['ReadingPlan_ID'].unique()

    for job in existing_jobs:
        job_id_parts = job.id.split('-')
        if len(job_id_parts) > 0 and int(job_id_parts[0]) in imported_ids:
            try:
                scheduler.remove_job(job.id)
                print(f"Removed existing job: {job.id}")
            except JobLookupError:
                print(f"Job not found for removal: {job.id}")

    # Schedule messages
    for index, row in data.iterrows():
        try:
            # Print raw values for debugging
            print(f"\nProcessing row {index}:")
            print(f"Reading Plan ID: {row['ReadingPlan_ID']} (Type: {type(row['ReadingPlan_ID'])})")
            print(f"Raw Date: {row['Date']}")
            print(f"Raw Time: {row['Time']}")
            print(f"Raw Bible Verse: {row['Bible_Verse']}")

            # Parse multiple verses
            bible_verses = [v.strip() for v in row['Bible_Verse'].split(",")]

            # Convert date and time, handling various input formats
            date_str = str(row['Date']).strip()
            time_str = str(row['Time']).strip()

            # Remove ' 00:00:00' if present
            if ' 00:00:00' in date_str:
                date_str = date_str.replace(' 00:00:00', '')

            # Combine date and time
            datetime_str = f"{date_str} {time_str}"
            print(f"Combined Datetime String: {datetime_str}")

            # Try multiple date formats
            date_formats = [
                "%Y-%m-%d %H:%M:%S",  # Full datetime
                "%Y-%m-%d %H:%M",     # Datetime without seconds
                "%m/%d/%Y %H:%M",     # Alternative format
                "%d-%b-%y %H:%M",     # Another format
                "%Y-%m-%d"            # Date only
            ]

            # Try parsing with different formats
            schedule_time = None
            for fmt in date_formats:
                try:
                    schedule_time = datetime.strptime(datetime_str, fmt)
                    print(f"Successfully parsed with format: {fmt}")
                    break
                except ValueError:
                    print(f"Failed to parse with format: {fmt}")
                    continue

            if not schedule_time:
                raise ValueError(f"Could not parse date: {datetime_str}")

            # Localize to Asia/Jakarta timezone
            schedule_time = jakarta_tz.localize(schedule_time)

            # Convert ReadingPlan_ID to string for job_id
            job_id = f"{row['ReadingPlan_ID']}-{schedule_time}"

            #Schedule the job
            scheduler.add_job(
                send_bible_verse,
                trigger='date',
                run_date=schedule_time,
                args=[target_channel, bible_verses, row['ReadingPlan_ID']],
                id=job_id
            )

            print(f"Scheduled job: {job_id}")
        except Exception as e:
            print(f"Error scheduling message: {e}")
            await interaction.followup.send(f"Error scheduling message for Reading Plan ID {row['ReadingPlan_ID']}: {e}")
            continue

    await interaction.followup.send("Reading plan imported and messages scheduled successfully!")


# Autocomplete function for channel_name
@import_schedule.autocomplete("channel_name")
async def autocomplete_channel_name(interaction: discord.Interaction, current: str):
    print(f"Autocomplete triggered. Current input: {current}")
    
    # Fetch all text channels in the guild
    guild = interaction.guild
    if not guild:
        print("No guild found")
        return []
    
    # Use a dictionary to track unique channel names (case-insensitive)
    channel_suggestions = {}
    
    # Collect unique channel suggestions
    for channel in guild.text_channels:
        # Convert to lowercase for case-insensitive comparison
        lower_name = channel.name.lower()
        
        # Check if the current input is in the channel name (case-insensitive match)
        if current.lower() in lower_name:
            # Only keep the first occurrence of a channel name
            if lower_name not in channel_suggestions:
                channel_suggestions[lower_name] = channel.name
    
    # Sort the suggestions
    sorted_suggestions = sorted(channel_suggestions.values())

    # Debugging output
    print(f"Unique channel suggestions: {sorted_suggestions}")

    # Return the suggestions in a list of `Choice` objects
    return [discord.app_commands.Choice(name=channel, value=channel) for channel in sorted_suggestions[:25]]

    
# Command to list scheduled messages
@bot.tree.command(name="list_schedules")
async def list_schedules(interaction: discord.Interaction):
    jobs = scheduler.get_jobs()
    if not jobs:
        await interaction.response.send_message("No messages are currently scheduled.")
        return

    response = "Scheduled Messages:\n"
    for job in jobs:
        # Extract the ReadingPlan_ID from the job ID
        reading_plan_id = job.id.split('-')[0]
        
        # Format the time in the desired format
        job_time = job.next_run_time.strftime("%d-%b-%Y at time %H:%M:%S")
        
        response += f"* ID: {reading_plan_id}, Scheduled for: {job_time}\n"

    await interaction.response.send_message(response)

# Command to delete a scheduled message
@bot.tree.command(name="delete_schedule")
@app_commands.describe(reading_plan_id = "Which message you want to delete?")
async def delete_schedule(interaction: discord.Interaction, reading_plan_id: str):
    jobs = scheduler.get_jobs()
    deleted = False

    for job in jobs:
        # Extract the ReadingPlan_ID from the job ID
        if job.id.startswith(f"{reading_plan_id}-"):
            try:
                scheduler.remove_job(job.id)
                deleted = True
                print(f"Deleted job: {job.id}")
            except JobLookupError:
                print(f"Job not found: {job.id}")
    
    if deleted:
        await interaction.response.send_message(f"Successfully deleted schedules with Reading Plan ID: {reading_plan_id}")
    else:
        await interaction.response.send_message(f"No schedules found with Reading Plan ID: {reading_plan_id}")

# Function to send Bible verses with hyperlinks and tracking button
async def send_bible_verse(channel, verses, reading_plan_id):
    # Get the current date in the format you used in the import
    current_date = datetime.now(jakarta_tz).strftime("%Y-%m-%d")
    
    messages = []
    for verse in verses:
        hyperlink = generate_bible_hyperlink(verse.strip())
        messages.append(f"- {hyperlink}")

    # Combine messages with new lines
    final_message = "\n".join(messages)
    
    # Create a view with a "Done" button
    class ReadingDoneView(discord.ui.View):
        def __init__(self, reading_plan_id, date, verses):
            super().__init__()
            self.reading_plan_id = reading_plan_id
            self.date = date
            self.verses = ", ".join(verses)
            # Track users who have already clicked
            self.users_reported = set()

        @discord.ui.button(label="Done Read", style=discord.ButtonStyle.green)
        async def mark_done(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Defer the response immediately to prevent timeout
            await interaction.response.defer(ephemeral=True)
            
            # Get the user's server nickname or username
            username = interaction.user.display_name or interaction.user.name
            
            # Check if user has already reported
            if username in self.users_reported:
                try:
                    await interaction.followup.send(
                        f"Hello, {interaction.user.mention}! Your reading record was already saved before."
                    )
                except discord.errors.NotFound:
                    # Fallback if the original interaction has timed out
                    await interaction.channel.send(
                        f"Hello, {interaction.user.mention}! Your reading record was already saved before."
                    )
                return
            
            # Save the reading report
            report_saved = save_reading_report(
                self.reading_plan_id, 
                username, 
                date=self.date, 
                bible_verse=self.verses
            )
            
            try:
                if report_saved:
                    # Add user to reported set
                    self.users_reported.add(username)
                    
                    await interaction.followup.send(
                        f"Thanks, {interaction.user.mention}! Your reading for these verses has been recorded."
                    )
                else:
                    await interaction.followup.send(
                        f"Sorry, {interaction.user.mention}. There was an issue saving your reading record."
                    )
            except discord.errors.NotFound:
                # Fallback method if interaction has timed out
                if report_saved:
                    await interaction.channel.send(
                        f"Thanks, {interaction.user.mention}! Your reading for these verses has been recorded."
                    )
                else:
                    await interaction.channel.send(
                        f"Sorry, {interaction.user.mention}. There was an issue saving your reading record."
                    )

    # Send message with the "Done" button
    await channel.send(final_message, view=ReadingDoneView(reading_plan_id, current_date, verses))

# Run bot
async def main():
    async with bot:
        # Start the bot
        await bot.start(TOKEN)

if __name__ == "__main__":
    # Run both Discord bot and HTTP server
    asyncio.run(main())