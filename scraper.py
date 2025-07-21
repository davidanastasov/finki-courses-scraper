from playwright.sync_api import sync_playwright
from time import sleep
import questionary
import json
import os
import asyncio
import re
from markdownify import markdownify as md

# Configuration
BASE_URL = "https://courses.finki.ukim.mk"
COOKIES_FILE = "cookies.json"
MINIMAL_WORKING_CODE = """int main() {
  return 0;
}
"""

COURSES = [
    "Сп-2024/2025/Z",
    "ОOП-2024/2025/L-46_42822"
]

def load_cookies(page):
    """Load saved cookies if they exist."""
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, 'r') as f:
                cookies = json.load(f)
            page.context.add_cookies(cookies)
            print("Loaded saved cookies")
            return True
        except Exception as e:
            print(f"Failed to load cookies: {e}")
            return False
    return False

def save_cookies(page):
    """Save current cookies to file."""
    try:
        cookies = page.context.cookies()
        with open(COOKIES_FILE, 'w') as f:
            json.dump(cookies, f)
        print("Cookies saved successfully")
        return True
    except Exception as e:
        print(f"Failed to save cookies: {e}")
        return False

def login(page):
    """Handle login process."""
    login_link = page.query_selector("a:has-text('Log in')")
    
    if login_link:
        print("Login required, proceeding with login...")
        login_link.click()
        
        # Find username and password fields
        username_field = page.query_selector("#username")
        password_field = page.query_selector("#password")
        submit_button = page.query_selector(".btn-submit")

        # Handle questionary prompts with event loop management
        def get_credentials():
            # Try to get the current event loop
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            
            # If there's a running loop, we need to handle it differently
            if current_loop is not None:
                # Run questionary in a thread to avoid event loop conflicts
                import concurrent.futures
                
                def run_questionary():
                    # Create a new event loop for this thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        username = questionary.text("Enter your username:").ask()
                        password = questionary.password("Enter your password:").ask()
                        return username, password
                    finally:
                        new_loop.close()
                
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_questionary)
                    return future.result()
            else:
                # No event loop running, can use questionary directly
                username = questionary.text("Enter your username:").ask()
                password = questionary.password("Enter your password:").ask()
                return username, password

        username, password = get_credentials()

        if username_field and password_field and submit_button:
            username_field.fill(username)
            password_field.fill(password)
            submit_button.click()
            print("Login submitted")
            sleep(3)
            
            # Save cookies after successful login
            save_cookies(page)
            return True
        else:
            print("Login fields or button not found")
            return False
    else:
        print("Already logged in, skipping login process")
        return True

def get_quiz_groups(page):
    """Extract quiz groups from the current course page."""
    sections = page.query_selector_all("li.section.main")
    quiz_groups = {}

    for section in sections:
        # Extract the section name
        section_name = section.query_selector(".sectionname span")
        if section_name:
            section_name_text = section_name.inner_text().strip()

            # Find all quiz links within this section
            quiz_links = section.query_selector_all("a.aalink:has(.accesshide:text(' Quiz'))")
            quiz_list = []
            for link in quiz_links:
                instancename = link.query_selector(".instancename")
                if instancename:
                    # Get all text nodes of instancename, excluding nested elements
                    quiz_name = instancename.evaluate("el => el.childNodes[0].textContent").strip()
                    quiz_list.append({
                        'name': quiz_name,
                        'url': link.get_attribute("href"),
                        'type': 'quiz'
                    })

            if quiz_list:
                quiz_groups[section_name_text] = quiz_list

    return quiz_groups

def get_all_resources(page):
    """Extract all resources (PDFs, URLs, Quizzes) grouped by sections."""
    sections = page.query_selector_all("li.section.main")
    resource_groups = {}

    for section in sections:
        # Extract the section name
        section_name = section.query_selector(".sectionname span")
        if section_name:
            section_name_text = section_name.inner_text().strip()
            resource_list = []

            # Find PDF files (mod/resource)
            pdf_links = section.query_selector_all("a.aalink[href*='mod/resource']")
            for link in pdf_links:
                instancename = link.query_selector(".instancename")
                if instancename:
                    resource_name = instancename.evaluate("el => el.childNodes[0].textContent").strip()
                    resource_list.append({
                        'name': f"📄 {resource_name}",
                        'url': link.get_attribute("href"),
                        'type': 'pdf',
                        'display_name': resource_name
                    })

            # Find URL links (mod/url)
            url_links = section.query_selector_all("a.aalink[href*='mod/url']")
            for link in url_links:
                instancename = link.query_selector(".instancename")
                if instancename:
                    resource_name = instancename.evaluate("el => el.childNodes[0].textContent").strip()
                    resource_list.append({
                        'name': f"🔗 {resource_name}",
                        'url': link.get_attribute("href"),
                        'type': 'url',
                        'display_name': resource_name
                    })

            # Find quizzes
            quiz_links = section.query_selector_all("a.aalink:has(.accesshide:text(' Quiz'))")
            for link in quiz_links:
                instancename = link.query_selector(".instancename")
                if instancename:
                    quiz_name = instancename.evaluate("el => el.childNodes[0].textContent").strip()
                    resource_list.append({
                        'name': f"📝 {quiz_name}",
                        'url': link.get_attribute("href"),
                        'type': 'quiz',
                        'display_name': quiz_name
                    })

            if resource_list:
                resource_groups[section_name_text] = resource_list

    return resource_groups

def select_all_resources(resource_groups):
    """Prompt user to select all types of resources (PDFs, URLs, Quizzes) grouped by sections."""
    
    # Create a single list of choices with separators for sections
    all_choices = []
    
    for section_name, resources in resource_groups.items():
        if not resources:  # Skip empty sections
            continue
        
        # Add section separator
        all_choices.append(questionary.Separator(f"=== {section_name} ==="))
        
        # Add resource choices for this section
        for resource in resources:
            all_choices.append(questionary.Choice(title=resource['name'], value=resource))
    
    # Show single checkbox prompt with all sections
    if all_choices:
        # Try to get the current event loop
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        
        # If there's a running loop, we need to handle it differently
        if current_loop is not None:
            # Run questionary in a thread to avoid event loop conflicts
            import concurrent.futures
            import threading
            
            def run_questionary():
                # Create a new event loop for this thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return questionary.checkbox(
                        "Select resources to download (📄 PDFs, 🔗 URLs, 📝 Quizzes):",
                        choices=all_choices
                    ).ask()
                finally:
                    new_loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_questionary)
                selected_resources = future.result()
        else:
            # No event loop running, can use questionary directly
            selected_resources = questionary.checkbox(
                "Select resources to download (📄 PDFs, 🔗 URLs, 📝 Quizzes):",
                choices=all_choices
            ).ask()
        
        if selected_resources:
            print(f"\nSelected {len(selected_resources)} resource(s) total")
            return selected_resources
        else:
            print("No resources selected")
            return []
    else:
        print("No resources found")
        return []

def download_pdf_resource(page, resource, course_folder):
    """Download a PDF resource."""
    try:
        # Create downloads folder
        pdf_folder = os.path.join(course_folder, "documents")
        os.makedirs(pdf_folder, exist_ok=True)
        
        # Set up download handling
        def handle_download(download):
            # Get the suggested filename or create one
            suggested_name = download.suggested_filename
            if not suggested_name or not suggested_name.endswith('.pdf'):
                suggested_name = f"{clean_filename(resource['display_name'])}.pdf"
            
            download_path = os.path.join(pdf_folder, suggested_name)
            download.save_as(download_path)
            print(f"PDF downloaded: {suggested_name}")
        
        # Listen for downloads
        page.on("download", handle_download)
        
        # Navigate to the PDF URL - this should trigger the download
        try:
            page.goto(resource['url'], wait_until="domcontentloaded")
        except Exception:
            # Download might have started immediately, that's expected
            pass
        
        sleep(1)  # Brief wait for download to start
        
        # Remove the download listener
        page.remove_listener("download", handle_download)
        
        return True
        
    except Exception as e:
        print(f"Error downloading PDF {resource['display_name']}: {e}")
        return False

def open_url_resource(page, resource, course_folder):
    """Open and capture a URL resource."""
    try:
        # Navigate to the URL using the existing page
        page.goto(resource['url'])
        sleep(1)
        
        current_url = page.url
        
        # Check if we got redirected outside the base domain (scenario 2)
        if not current_url.startswith(BASE_URL):
            # External redirect - save the redirected URL
            url_folder = os.path.join(course_folder, "links")
            os.makedirs(url_folder, exist_ok=True)
            
            url_info_path = os.path.join(url_folder, f"{clean_filename(resource['display_name'])}.txt")
            with open(url_info_path, 'w', encoding='utf-8') as f:
                f.write(f"Name: {resource['display_name']}\n")
                f.write(f"URL: {current_url}\n")
            
            print(f"URL extracted: {resource['display_name']} -> {current_url}")
            return True
        
        # We're still on the base domain - check for scenario 1 (urlworkaround div)
        urlworkaround_div = page.query_selector(".urlworkaround")
        if urlworkaround_div:
            # Extract the actual link from the urlworkaround div
            link_element = urlworkaround_div.query_selector("a")
            if link_element:
                actual_url = link_element.get_attribute("href")
                
                # Save the extracted URL info
                url_folder = os.path.join(course_folder, "links")
                os.makedirs(url_folder, exist_ok=True)
                
                url_info_path = os.path.join(url_folder, f"{resource['display_name']}.txt")
                with open(url_info_path, 'w', encoding='utf-8') as f:
                    f.write(f"Name: {resource['display_name']}\n")
                    f.write(f"URL: {actual_url}\n")
                
                print(f"URL extracted: {resource['display_name']} -> {actual_url}")
                return True
        
        raise Exception("No way to extract URL from the page")
        
    except Exception as e:
        print(f"Error capturing URL {resource['display_name']}: {e}")
        return False

def clean_filename(name):
    """Clean a string to be used as a filename."""
    clean_name = re.sub(r'[^\w\s-]', '', name).strip()
    return re.sub(r'\s+', '_', clean_name)

def remove_header_and_footer(page):
    """Hide PII from the page header and footer for privacy in screenshots."""
    try:
        page.evaluate("""
            document.querySelectorAll('.navbar').forEach(el => el.remove());
            document.querySelectorAll('footer').forEach(el => el.remove());
        """)

        # Wait for the nav and footer elements to be removed
        page.wait_for_selector('.navbar', state='detached', timeout=3000)  # 3-second timeout
        page.wait_for_selector('footer', state='detached', timeout=3000)  # 3-second timeout

    except Exception as e:
        print(f"Could not hide user name: {e}")


def remove_unwanted_elements(page):
    """Remove unwanted UI elements from the page content."""
    for _ in range(10):  # Try up to 10 times in case of race conditions
        page.evaluate("""
            const contentDiv = document.querySelector('div.content');
            if (contentDiv) {
                contentDiv.querySelectorAll('.ui_wrapper').forEach(el => { el.remove() });
                contentDiv.querySelectorAll('.im-controls').forEach(el => { el.remove() });
                contentDiv.querySelectorAll('.prompt').forEach(el => { el.remove() });
                contentDiv.querySelector('textarea.coderunner-answer')?.remove()
                contentDiv.querySelector('#goto-top-link')?.remove();
            }
        """)
        sleep(0.1)
        if (page.query_selector("div.content .ui_wrapper") is None and 
            page.query_selector("div.content .im-controls") is None and 
            page.query_selector("div.content .prompt") is None) and \
            page.query_selector("div.content textarea.coderunner-answer") and \
            page.query_selector("div.content #goto-top-link") is None:
            break

def ensure_question_fully_loaded(page):
    """Ensure the question is fully loaded by submitting minimal code if needed."""
    content_div = page.query_selector("div.content")
    if not content_div:
        return None

    # If no valid answer is provided, the question won't show all the test cases
    # Insert a sample code to ensure the question is fully loaded
    outcome_section = content_div.query_selector(".outcome table")
    if not outcome_section:
        page.evaluate(f"document.querySelector('textarea.coderunner-answer').value = `{MINIMAL_WORKING_CODE}`;")

        # Type submit, value Check
        check_answer_button = page.query_selector("input[type='submit'][value='Check']")
        if check_answer_button:
            check_answer_button.click()
            sleep(3) # Wait for the page to update with test results
        else:
            print("No 'Check' button found, only partial output will be available.")


def extract_question_content(page):
    """Extract and convert question content to markdown."""
    content_div = page.query_selector("div.content")
    if not content_div:
        return None
    
    # Save starter code if found
    starter_code = ""
    reset_button = page.query_selector("input[type='button'].answer_reset_btn")
    if reset_button:
        reload_text = reset_button.get_attribute("data-reload-text")
        if reload_text:
            starter_code = reload_text.strip()

    # Extract textarea content separately for proper code formatting
    textarea_content = ""
    textarea = page.query_selector("textarea.coderunner-answer")
    if textarea:
        textarea_content = textarea.input_value()
    
    # Remove unwanted  elements
    remove_unwanted_elements(page)

    sleep(0.5)

    # Get the cleaned HTML content
    content_html = content_div.inner_html()
    
    # Convert to markdown
    content_markdown = md(content_html, 
                        heading_style="ATX",
                        bullets="-",
                        code_language="",
                        strip=['script', 'style'])

    # If starter code is available, add it as a code block
    if starter_code.strip():
        content_markdown += f"\n\n## Starter Code:\n\n```cpp\n{starter_code.strip()}\n```\n"        
    
    # Add textarea content as a code block if it exists
    if textarea_content.strip() and textarea_content.strip() != MINIMAL_WORKING_CODE.strip():
        content_markdown += f"\n\n## Saved Code:\n\n```cpp\n{textarea_content.strip()}\n```\n"
    
    return content_markdown

def process_quiz_questions(page, quiz, course):
    """Process all questions in a quiz."""
    course_name_clean = clean_filename(course)
    quiz_name_clean = clean_filename(quiz['name'])
    output_folder = f"output/{course_name_clean}/{quiz_name_clean}"
    os.makedirs(output_folder, exist_ok=True)
    
    # Find all question navigation buttons
    question_buttons = page.query_selector_all("a.qnbutton")
    if not question_buttons:
        print("No question buttons found in quiz")
        return False
    
    print(f"Found {len(question_buttons)} questions in quiz")
    
    # Store question data
    questions = []
    for button in question_buttons:
        question_number = button.inner_text().strip()
        question_link = button.get_attribute("href")
        solved = button.query_selector(".answersaved") is not None
        
        # If the link is "#", use the current page URL (for initially selected question)
        if question_link == "#":
            question_link = page.url
        
        # Extract only the numeric part from question number using regex
        number_match = re.search(r'\d+', question_number)
        clean_number = number_match.group() if number_match else question_number
        
        questions.append({
            'number': clean_number,
            'link': question_link,
            'completed': solved
        })
    
    # Process each question
    for question in questions:
        page.goto(question['link'])

        # Make sure all the page content is shown
        ensure_question_fully_loaded(page)

        # Remove PII
        remove_header_and_footer(page)

        # Extract content and save as markdown
        content_markdown = extract_question_content(page)
        if content_markdown:
            markdown_path = f"{output_folder}/{question['number']}.md"
            with open(markdown_path, 'w', encoding='utf-8') as f:
                f.write(content_markdown)
        else:
            print(f"No content found for question {question['number']}")

        # Take full page screenshot
        screenshots_subfolder = os.path.join(output_folder, "screenshots")
        os.makedirs(screenshots_subfolder, exist_ok=True)
        screenshot_path = f"{screenshots_subfolder}/{question['number']}.png"
        content_div = page.query_selector("div.content")
        if content_div:
            content_div.evaluate("el => el.style.width = '1366px'")
            content_div.screenshot(path=screenshot_path)
        
    
    print(f"Completed processing all questions in quiz '{quiz['name']}'")
    return True

def process_quiz(page, quiz):
    """Process a single quiz."""
    page.goto(quiz['url'])
    sleep(2)

    # Look for continue button
    continue_btn = page.query_selector("button[type='submit']:has-text('Continue the last attempt')")

    if (continue_btn is None):
        continue_btn = page.query_selector("button[type='submit']:has-text('Attempt quiz now')")
    
    if continue_btn:
        continue_btn.click()
        print(f"Continuing quiz: {quiz['name']}")
        sleep(3)
        return True
    else:
        print(f"No continue button found for quiz: {quiz['name']}")
        return False

def process_course(page, course):
    """Process a single course."""
    page.goto(BASE_URL)
    sleep(1)

    # Find the course link and click it
    course_link = page.query_selector(f"a:has-text('{course}')")
    if not course_link:
        print(f"Course link '{course}' not found")
        return False
    
    course_link.click()
    sleep(1)

    course_name_clean = clean_filename(course)
    course_folder = f"output/{course_name_clean}"
    os.makedirs(course_folder, exist_ok=True)

    # Capture course overview screenshot
    capture_course_overview(page, course_folder)

    # Get all resources (PDFs, URLs, Quizzes) and let user select
    print(f"\n=== Processing {course} ===")
    resource_groups = get_all_resources(page)
    
    if resource_groups:
        selected_resources = select_all_resources(resource_groups)
        
        if selected_resources:
            print("Selected resources:")
            for resource in selected_resources:
                print(f"- {resource['name']} ({resource['url']})")
            
            # Process each selected resource by type
            for resource in selected_resources:
                if resource['type'] == 'pdf':
                    download_pdf_resource(page, resource, course_folder)
                elif resource['type'] == 'url':
                    open_url_resource(page, resource, course_folder)
                elif resource['type'] == 'quiz':
                    if process_quiz(page, resource):
                        process_quiz_questions(page, resource, course)
    else:
        print("No resources found")

    return True

def select_quizzes(quiz_groups):
    """Prompt user to select quizzes grouped by sections with checkbox interface."""
    
    # Create a single list of choices with separators for sections
    all_choices = []
    
    for section_name, quizzes in quiz_groups.items():
        if not quizzes:  # Skip empty sections
            continue
        
        # Add section separator
        all_choices.append(questionary.Separator(f"=== {section_name} ==="))
        
        # Add quiz choices for this section
        for quiz in quizzes:
            all_choices.append(questionary.Choice(title=quiz['name'], value=quiz))
    
    # Show single checkbox prompt with all sections
    if all_choices:
        # Try to get the current event loop
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        
        # If there's a running loop, we need to handle it differently
        if current_loop is not None:
            # Run questionary in a thread to avoid event loop conflicts
            import concurrent.futures
            import threading
            
            def run_questionary():
                # Create a new event loop for this thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return questionary.checkbox(
                        "Select quizzes (use Space to select/deselect, Enter to confirm):",
                        choices=all_choices
                    ).ask()
                finally:
                    new_loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_questionary)
                selected_quizzes = future.result()
        else:
            # No event loop running, can use questionary directly
            selected_quizzes = questionary.checkbox(
                "Select quizzes (use Space to select/deselect, Enter to confirm):",
                choices=all_choices
            ).ask()
        
        if selected_quizzes:
            print(f"\nSelected {len(selected_quizzes)} quiz(s) total")
            return selected_quizzes
        else:
            print("No quizzes selected")
            return []
    else:
        print("No quizzes found")
        return []

def capture_course_overview(page, course_folder):
    """Capture a screenshot of the main course page."""
    try:
        # Remove header/footer for privacy using existing function
        remove_header_and_footer(page)
        
        # Find the main region element
        main_region = page.query_selector("#region-main")
        if main_region:
            # Take screenshot of the main region
            screenshot_path = os.path.join(course_folder, "course.png")
            main_region.screenshot(path=screenshot_path)
            print(f"Course overview screenshot saved: course.png")
            return True
        else:
            print("Main region not found, taking full page screenshot instead")
            screenshot_path = os.path.join(course_folder, "course.png")
            page.screenshot(path=screenshot_path, full_page=True)
            return True
            
    except Exception as e:
        print(f"Error capturing course overview: {e}")
        return False

def main():
    """Main function to run the scraper."""
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        page = browser.new_page()

        # Load cookies and navigate to the site
        load_cookies(page)
        page.goto(BASE_URL)
        sleep(1)  # Wait for page to load

        # Handle login if needed
        if not login(page):
            print("Login failed")
            browser.close()
            return

        # Process each course
        for course in COURSES:
            print(f"\nProcessing course: {course}")
            process_course(page, course)

        page.goto("about:blank") # Free up any still open resources

        browser.close()
        print("Scraping completed.")

if __name__ == "__main__":
    main()