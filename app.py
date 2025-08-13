from flask import Flask, render_template, request, send_file, flash, redirect, url_for
import google.generativeai as genai
import pandas as pd
import json
import re
import os
from datetime import datetime
import tempfile

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") # Change this to a secure secret key

# Configure Google AI Studio API
API_KEY= os.getenv("GOOGLE_AI_API_KEY")# Replace with your actual API key
genai.configure(api_key=API_KEY)

# Initialize the model
model = genai.GenerativeModel('gemini-1.5-flash')

def parse_mcq_response(response_text):
    """Parse the AI response to extract MCQ questions"""
    questions = []
    
    # Split by question numbers
    question_blocks = re.split(r'\n(?=\d+\.)', response_text.strip())
    
    for block in question_blocks:
        if not block.strip():
            continue
            
        lines = block.strip().split('\n')
        if len(lines) < 7:  # Skip incomplete questions
            continue
            
        try:
            # Extract question number and text
            question_line = lines[0]
            question_match = re.match(r'(\d+)\.\s*(.*)', question_line)
            if not question_match:
                continue
                
            s_no = question_match.group(1)
            question_text = question_match.group(2)
            
            # Extract options
            options = []
            correct_answer = None
            explanation = ""
            answer_letter = None
            
            for line in lines[1:]:
                line = line.strip()
                if re.match(r'^[A-D]\)', line):
                    options.append(line[3:].strip())
                elif any(keyword in line.lower() for keyword in ['correct answer:', 'answer:', 'correct:', 'right answer:']):
                    # Look for the answer letter more carefully with multiple patterns
                    answer_patterns = [
                        r'correct answer:\s*([A-D])',
                        r'answer:\s*([A-D])', 
                        r'correct:\s*([A-D])',
                        r'right answer:\s*([A-D])',
                        r'\b([A-D])\)',
                        r'\b([A-D])\b'
                    ]
                    
                    for pattern in answer_patterns:
                        answer_match = re.search(pattern, line.upper())
                        if answer_match:
                            answer_letter = answer_match.group(1)
                            correct_answer = ord(answer_letter) - ord('A') + 1
                            break
                            
                elif line.lower().startswith('explanation:'):
                    explanation = line[12:].strip()
            
            # Validation and debugging
            if len(options) == 4 and correct_answer and 1 <= correct_answer <= 4:
                questions.append({
                    'S. No.': int(s_no),
                    'Question': question_text,
                    'First Option': options[0],
                    'Second Option': options[1], 
                    'Third Option': options[2],
                    'Fourth Option': options[3],
                    'Right Answer No.': correct_answer,
                    'Explanation': explanation
                })
                print(f"✓ Question {s_no}: Answer {answer_letter} = {correct_answer}")
            else:
                print(f"✗ Skipped Question {s_no}: Options={len(options)}, Answer={correct_answer}, Letter={answer_letter}")
                
        except Exception as e:
            print(f"Error parsing question block: {e}")
            continue
    
    return questions

def generate_mcq_questions(board, class_name, subject, chapter, difficulty):
    """Generate MCQ questions using Google AI Studio"""
    
    prompt = f"""
    Generate exactly 20 multiple choice questions for the following specifications:
    - Board of Education: {board}
    - Class: {class_name}
    - Subject: {subject}
    - Chapter: {chapter}
    - Difficulty Level: {difficulty}
    
    IMPORTANT: Make sure the correct answers are distributed randomly across options A, B, C, and D. Do NOT put all correct answers in the same option position. Mix them up naturally - some questions should have A as correct, some B, some C, some D.
    
    Format each question exactly as follows:
    
    1. [Question text here]
    A) [First option]
    B) [Second option]
    C) [Third option]
    D) [Fourth option]
    Correct Answer: [A/B/C/D]
    Explanation: [Brief explanation of why this answer is correct]
    
    2. [Next question...]
    
    Requirements:
    - Make sure each question is relevant to the chapter topic and appropriate for the class level and difficulty specified
    - Provide clear, unambiguous questions with one definitively correct answer
    - Distribute correct answers randomly: roughly 5 questions each should have A, B, C, or D as the correct answer
    - Ensure all incorrect options are plausible but clearly wrong
    - Vary the question types (definition, application, analysis, etc.)
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating content: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    try:
        # Get form data
        board = request.form.get('board')
        class_name = request.form.get('class')
        subject = request.form.get('subject')
        chapter = request.form.get('chapter')
        difficulty = request.form.get('difficulty')
        
        # Validate inputs
        if not all([board, class_name, subject, chapter, difficulty]):
            flash('All fields are required!')
            return redirect(url_for('index'))
        
        # Generate MCQ questions
        flash('Generating questions... Please wait.')
        ai_response = generate_mcq_questions(board, class_name, subject, chapter, difficulty)
        
        if not ai_response:
            flash('Error generating questions. Please try again.')
            return redirect(url_for('index'))
        
        # Parse the response
        questions = parse_mcq_response(ai_response)
        
        if len(questions) == 0:
            flash('No questions could be parsed. Please try again.')
            return redirect(url_for('index'))
        
        # Create DataFrame
        df = pd.DataFrame(questions)
        
        # Ensure we have the right columns in the right order
        column_order = ['S. No.', 'Question', 'First Option', 'Second Option', 
                       'Third Option', 'Fourth Option', 'Right Answer No.', 'Explanation']
        df = df.reindex(columns=column_order)
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        temp_filename = temp_file.name
        temp_file.close()
        
        # Save to Excel
        with pd.ExcelWriter(temp_filename, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='MCQ Questions')
            
            # Auto-adjust column widths
            worksheet = writer.sheets['MCQ Questions']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        # Generate filename
        safe_chapter = re.sub(r'[^\w\-_\.]', '_', chapter)
        filename = f"MCQ_{safe_chapter}_{class_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            temp_filename,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        flash(f'An error occurred: {str(e)}')
        return redirect(url_for('index'))

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    

    app.run(debug=True)


