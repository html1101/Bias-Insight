import os, copy, re
from fastapi import FastAPI, HTTPException, Depends

app = FastAPI()

from sqlalchemy import and_, create_engine, Column, Integer, Float, String, JSON, func, Boolean, not_, or_
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from typing import List, Dict, Tuple
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, PreTrainedModel, PreTrainedTokenizer
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
# Added to get the day we make a query
from datetime import datetime
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy import PickleType

from collections import defaultdict
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
nltk.download('stopwords')
nltk.download('punkt_tab')
from label_message import label_messages

#import ssl
#ssl._create_default_https_context = ssl._create_unverified_context


SPECIAL_CHARS = ",!?:;@#$%^&*()\"'+1234567890/–=-{}`~<>[]\\_·›”’“"
# Store only the top 75 BoWs
MAX_BOW = 75

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables.")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()




app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

device = "cpu"

###
# Global references (initialized to None, so we know they aren't loaded)
###
web_class_model = None
web_class_tokenizer = None

sentiment_model = None
sentiment_tokenizer = None

emotion_model = None
emotion_tokenizer = None

political_model = None
political_tokenizer = None

stereo_model = None
stereo_tokenizer = None

emotion_labels = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]
stereo_labels = ["unrelated", "stereotype_gender", "stereotype_race", "stereotype_profession", "stereotype_religion"]
political_labels = ["left", "center", "right"]
web_class_labels = [
    "Adult", "Art & Design", "Software Dev.", "Crime & Law", "Education & Jobs",
    "Hardware", "Entertainment", "Social Life", "Fashion & Beauty", "Finance & Business",
    "Food & Dining", "Games", "Health", "History", "Home & Hobbies", "Industrial",
    "Literature", "Politics", "Religion", "Science & Tech.", "Software",
    "Sports & Fitness", "Transportation", "Travel"
]

###
# Lazy Loading
# Only load the model/tokenizer once, then reuse.
###

def get_web_class_model():
    global web_class_model, web_class_tokenizer
    if web_class_model is None:
        web_class_model = AutoModelForSequenceClassification.from_pretrained(
            "WebOrganizer/TopicClassifier",
            trust_remote_code=True,
            use_memory_efficient_attention=False
        ).to(device)
        web_class_tokenizer = AutoTokenizer.from_pretrained(
            "WebOrganizer/TopicClassifier",
            trust_remote_code=True
        )
    return web_class_model, web_class_tokenizer


def get_sentiment_model():
    global sentiment_model, sentiment_tokenizer
    if sentiment_model is None:
        sentiment_model = AutoModelForSequenceClassification.from_pretrained(
            "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
        ).to(device)
        sentiment_tokenizer = AutoTokenizer.from_pretrained(
            "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
        )
    return sentiment_model, sentiment_tokenizer


def get_emotion_model():
    global emotion_model, emotion_tokenizer
    if emotion_model is None:
        emotion_model = AutoModelForSequenceClassification.from_pretrained(
            "j-hartmann/emotion-english-distilroberta-base"
        ).to(device)
        emotion_tokenizer = AutoTokenizer.from_pretrained(
            "j-hartmann/emotion-english-distilroberta-base"
        )
    return emotion_model, emotion_tokenizer


def get_political_model():
    global political_model, political_tokenizer
    if political_model is None:
        political_model = AutoModelForSequenceClassification.from_pretrained(
            "premsa/political-bias-prediction-allsides-BERT"
        ).to(device)
        political_tokenizer = AutoTokenizer.from_pretrained(
            "premsa/political-bias-prediction-allsides-BERT"
        )
    return political_model, political_tokenizer


def get_stereo_model():
    global stereo_model, stereo_tokenizer
    if stereo_model is None:
        stereo_model = AutoModelForSequenceClassification.from_pretrained(
            "wu981526092/Sentence-Level-Stereotype-Detector"
        ).to(device)
        stereo_tokenizer = AutoTokenizer.from_pretrained(
            "wu981526092/Sentence-Level-Stereotype-Detector"
        )
    return stereo_model, stereo_tokenizer


def add_to_json(json, added, labels, time, prev_time):
    new_json = copy.deepcopy(json)
    if not json:
        new_json = {}
        for label in labels:
            new_json[label] = added[label]
    else:
        for label in labels:
            new_json[label] = (json[label] * prev_time + added[label] * time) / (time + prev_time)
    return new_json

def normalize_json(json, labels, time):
    # todo deep copy?
    new_json = json
    for label in labels:
        new_json[label] = new_json[label] * time
    return new_json

"""
A single viewing session of a website.
Contains analysis information from a single
viewing session.
TODO: Right now duplicative sessions override previous ones;
total viewing time is added up, but analyses are overridden.
"""
class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"
    id = Column(Integer, primary_key=True, index=True)
    website = Column(String, index=True)
    entry_time = Column(Float)
    exit_time = Column(Float, nullable=True)
    viewing_time = Column(Float, default=0.0)
    sentiment_score = Column(Float)
    emotions = Column(JSON)
    political_bias = Column(JSON)
    stereotype_score = Column(JSON)

def word_extraction(sentence):
    stop_words = set(stopwords.words('english'))
 
    word_tokens = word_tokenize(sentence)
    # converts the words in word_tokens to lower case and then checks whether 
    #they are present in stop_words or not
    filtered_sentence = [w for w in word_tokens if not w.lower() in stop_words]
    #with no lower case conversion
    filtered_sentence = []
    
    for w in word_tokens:
        if w.lower() not in stop_words:
            filtered_sentence.append(w.lower())
    
    return filtered_sentence

def tokenize(sentences):
    words = []
    for sentence in sentences:
        w = word_extraction(sentence.translate({ord(x): '' for x in SPECIAL_CHARS}))
        words.extend(w)
        words = sorted(list(set(words)))
    return words

def generate_bow(allsentences):
    vocab = tokenize(allsentences)

    bag_vector = [0 for _ in range(len(vocab))]
    for sentence in allsentences:
        words = word_extraction(sentence)
        for w in words:
            for i,word in enumerate(vocab):
                if word == w:
                    bag_vector[i] += 1
    return list(sorted(zip(vocab, bag_vector), key=lambda x: -x[1]))


"""
Aggregated information about what specific words/
phrases show up most often ALL TIME
"""
class AnalysisBoW(Base):
    __tablename__ = "analysis_bow"
    id = Column(Integer, primary_key=True, index=True)
    bow = Column(MutableList.as_mutable(PickleType))
    def to_string(self):
        return [ (vocab, bow) for vocab, bow in self.bow ]

"""
A viewing session for a single day.
Contains weighted averages of each session from a
given day (day/month/year)
"""
class AnalysisSessionDay(Base):
    __tablename__ = "analysis_day"
    id = Column(Integer, primary_key=True, index=True)
    # website = Column(String, index=True)
    today = Column(Boolean, default=False, index=True)
    # dd/mm/yyyy
    day = Column(String)
    # total amount of time viewing content
    viewing_time = Column(Float, default=0.0)
    # number of websites visited
    number_websites = Column(Integer, default=0)

    # aggregate measurements of analyses done on each website
    sentiment_score = Column(Float)
    emotions = Column(JSON)
    political_bias = Column(JSON)
    stereotype_score = Column(JSON)
    def as_dict(self):
        return {
            "day": self.day,
            # Give back viewing time in seconds
            "viewing_time": self.viewing_time,
            "number_websites": self.number_websites,
            "sentiment_score": self.sentiment_score / self.viewing_time,
            "emotions": self.emotions,
            "political_bias": self.political_bias,
            "stereotype_score": self.stereotype_score,
        }
    
class WebsiteClassification (Base):
    __tablename__ ="website_classifications"
    id=Column(Integer,primary_key=True, index=True)
    label=Column(String, nullable=False)


Base.metadata.create_all(bind=engine)

class TextInput(BaseModel):
    data: str
    website: str
    entry_time: float

class TimeUpdate(BaseModel):
    website: str
    exit_time: float

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_timestamp():
    # see: https://stackoverflow.com/questions/55113548/get-year-month-and-day-from-python-variable
    now = datetime.now()
    dmy_format = '%d-%m-%Y (%H)'
    return now.strftime(dmy_format)

def get_day():
    # see: https://stackoverflow.com/questions/55113548/get-year-month-and-day-from-python-variable
    now = datetime.now()
    dmy_format = '%d-%m-%Y'
    return now.strftime(dmy_format)

def combine_bow(bag1, bag2):
    # Create a dictionary to store the maximum significance
    combined_bag = defaultdict(int)
    
    # Take the maximum significance for words in bag1
    for word, number in bag1:
        combined_bag[word] += number
    
    # Take the maximum significance for words in bag2
    for word, number in bag2:
        combined_bag[word] += number
    
    # Convert the dictionary back into a list of tuples
    return list(combined_bag.items())

async def classify_texts(model_and_tokenizer: Tuple[PreTrainedModel, PreTrainedTokenizer], texts):
    model, tokenizer = model_and_tokenizer
    inputs = tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    return torch.nn.functional.softmax(outputs.logits, dim=-1).cpu().numpy().tolist()  # Convert tensors to lists

async def classify_websites(model, tokenizer, website, text):
    try:
        model, tokenizer = get_web_class_model()
        combined_input = f"{website} {text}"
        inputs = tokenizer(combined_input, return_tensors="pt", truncation=True, padding=True).to(device)
        
        with torch.no_grad():
            outputs = model(**inputs)       
        
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
        predicted_index = probs.argmax(dim=-1).cpu().item()
        
        return predicted_index

    except Exception as e:
        print(f"Error in classify_websites: {str(e)}")
        raise e

@app.post("/webclass")
async def class_webs(input_data: TextInput, db: Session = Depends(get_db)):
    
    if not input_data.website or not input_data.data:
        raise HTTPException(status_code=400, detail="Both website and text data are required.")
          
    web_classification_index = await classify_websites(web_class_model, web_class_tokenizer, input_data.website,input_data.data)
    
    record = WebsiteClassification(
        label=web_class_labels[web_classification_index]
    )
    db.add(record)
    db.commit()

    return {
        "website_classification": web_class_labels[web_classification_index]
    }


@app.post("/SMBSanalyze")
async def analyze_texts(input_data: TextInput, db: Session = Depends(get_db)):
    print(F"User just entered {input_data.website}.")
    data = input_data.data
    if not data:
        raise HTTPException(status_code=400, detail="Input texts cannot be empty.")
    
    sentiment_scores = await classify_texts(get_sentiment_model(), [data])
    batch_sentiment_score = round(sum(score[1] - score[0] for score in sentiment_scores) / len(sentiment_scores), 4)

    emotion_scores = await classify_texts(get_emotion_model(), [data])
    batch_emotions = {label: round(sum(em[i] for em in emotion_scores) / len(emotion_scores), 4) for i, label in enumerate(emotion_labels)}

    political_scores = await classify_texts(get_political_model(), [data])
    batch_political_bias = {label: round(sum(pol[i] for pol in political_scores) / len(political_scores), 4) for i, label in enumerate(political_labels)}

    stereotype_scores = await classify_texts(get_stereo_model(), [data])
    batch_stereotypes = {label: round(sum(st[i] for st in stereotype_scores) / len(stereotype_scores), 4) for i, label in enumerate(stereo_labels)}

    response = {
        "sentiment_score": batch_sentiment_score,
        "emotions": batch_emotions,
        "political_bias": batch_political_bias,
        "stereotype": batch_stereotypes
    }

    session = AnalysisSession(
        website=input_data.website,
        entry_time=input_data.entry_time,
        sentiment_score=batch_sentiment_score,  
        emotions=batch_emotions if batch_emotions else {}, 
        political_bias=batch_political_bias if batch_political_bias else {}, 
        stereotype_score=batch_stereotypes if batch_stereotypes else {}  
    )
    db.add(session)
    db.commit()

    splitter = re.compile(r"\.|\n")
    bow = generate_bow(splitter.split(data))
    print("Got bow: ", bow)
    session = db.query(AnalysisBoW).first()
    # If we have one, add to it. If we don't, add a new entry
    if session:
        # Come up with new bow + vocab that's combined
        session.bow = list(sorted(combine_bow(bow, session.bow), key=lambda x: -x[1]))[:MAX_BOW]
    else:
        newBow = AnalysisBoW(
            bow = bow
        )
        db.add(newBow)
    db.commit()

    # Add to our collected information
    # collected_bow = db.query

    return response

@app.get("/get_bow")
async def get_bow(db: Session = Depends(get_db)):
    session = db.query(AnalysisBoW).first()

    if session:
        return session.to_string()
    else:
        raise HTTPException(status_code=404, detail="BoW not found")

@app.patch("/update_viewing_time")
async def update_viewing_time(time_data: TimeUpdate, db: Session = Depends(get_db)):
    print(F"User just left {time_data.website}.")
    session = db.query(AnalysisSession).filter(
        AnalysisSession.website == time_data.website
    ).order_by(AnalysisSession.entry_time.desc()).first()  # Get latest session for the website

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if time_data.exit_time <= session.entry_time:
        raise HTTPException(status_code=400, detail="Exit time must be greater than entry time.")

    session.exit_time = time_data.exit_time
    # If we've previously viewed this site, add to it
    if session.viewing_time:
        session.viewing_time += round(session.exit_time - session.entry_time, 4)
    else:
        session.viewing_time = round(session.exit_time - session.entry_time, 4)  # Ensure correct viewing time
    
    # Upon leaving a website,
    # update our current day's aggregate statistics
    # (1) Find if this day exists within the database already
    dmy = get_timestamp()

    def add_aggregate_point(dmy, today = False):
        current_day = db.query(AnalysisSessionDay).filter(
            or_(and_(AnalysisSessionDay.day == dmy, not_(AnalysisSessionDay.today)),
                and_(today, AnalysisSessionDay.today == True))
        ).first()

        # If today set and the day is not the same,
        # remove current_day and restart
        if (today and current_day and current_day.day != dmy):
            print("Day changed, removing element")
            db.delete(current_day)
            current_day = None

        # If day doesn't exist, add it to database
        if not current_day:
            print(F"Day {dmy} does not yet exist {current_day and current_day.day != dmy}, adding to database.")
            if today:
                print("(In today mode)")
            # Add our website's info + the day
            session_day = AnalysisSessionDay(
                day = dmy,
                today = today,
                # amt of timed viewed is just this website,
                # since we haven't gone anywhere else
                viewing_time = session.viewing_time,
                # number of websites visited--just this one
                number_websites = 1,

                # aggregate measurements of analyses done on each website
                sentiment_score = session.sentiment_score * session.viewing_time,
                emotions = add_to_json(
                    None, session.emotions, emotion_labels, session.viewing_time, 0
                ),
                political_bias = add_to_json(
                    None, session.political_bias, political_labels, session.viewing_time, 0
                ),
                stereotype_score = add_to_json(
                    None, session.stereotype_score, stereo_labels, session.viewing_time, 0
                )
            )
            # Add session to database
            db.add(session_day)
        else:
            print(F"Updating current day: {dmy}, {today}")
            # Update the existing day
            current_day.today = today
            current_day.number_websites += 1
            current_day.sentiment_score += session.sentiment_score * session.viewing_time
            # Add to the JSON-elements:
            current_day.emotions = add_to_json(
                current_day.emotions, session.emotions, emotion_labels, session.viewing_time, current_day.viewing_time
            )
            if today:
                print("BEFORE: ", current_day.political_bias, session.political_bias, "AFTER", add_to_json(
                    current_day.political_bias, session.political_bias, political_labels, session.viewing_time, current_day.viewing_time
                ))
            current_day.political_bias = add_to_json(
                current_day.political_bias, session.political_bias, political_labels, session.viewing_time, current_day.viewing_time
            )
            current_day.stereotype_score = add_to_json(
                current_day.stereotype_score, session.stereotype_score, stereo_labels, session.viewing_time, current_day.viewing_time
            )
            current_day.viewing_time += session.viewing_time

    # Add to a "today" aggregator--use for today's status
    add_aggregate_point(get_day(), True)
    add_aggregate_point(dmy)
    db.commit()

    return {"message": "Viewing time updated successfully"}

@app.get("/today")
async def get_day_stats(db: Session = Depends(get_db)):
    # Query database for the current day
    current_day = db.query(AnalysisSessionDay).filter(
        AnalysisSessionDay.today == True
    ).first()
    if current_day:
        print(F"Giving back day with: {current_day.day}")
        # Give back the information we have about this day
        return current_day.as_dict()
    else:
        # We don't have any info :(
        # Don't make this a 404 because
        # it's normal to query times that have no info for them
        return { "detail": "No info available for this day", "no_info": True }

# Given a day we are querying,
# give back the information we have for that specific day (nothing if we have no measurements).
@app.get("/day_stats")
async def get_day_stats(day, db: Session = Depends(get_db)):
    # Query database for this day
    print(F"User queried day: {day}")
    current_day = db.query(AnalysisSessionDay).filter(
        AnalysisSessionDay.day == day
    ).first()
    if current_day:
        # Give back the information we have about this day
        return current_day.as_dict()
    else:
        # We don't have any info :(
        # Don't make this a 404 because
        # it's normal to query times that have no info for them
        return { "detail": "No info available for this day", "no_info": True }

@app.get("/website_stats")
async def get_website_stats(db: Session = Depends(get_db)):
    stats = db.query(
        AnalysisSession.website,
        func.sum(AnalysisSession.viewing_time).label("total_time")
    ).group_by(AnalysisSession.website).all()

    if not stats:
        raise HTTPException(status_code=404, detail="No website statistics found")

    return [{"website": s[0], "total_viewing_time": round(s[1], 4)} for s in stats]


@app.get("/overall_results")
async def get_overall_accumulated_results(website: str = None, db: Session = Depends(get_db)):
    query = db.query(AnalysisSession).filter(AnalysisSession.viewing_time > 0)
    if website:
        query = query.filter(AnalysisSession.website == website)  # Filter by website if provided

    sessions = query.all()

    if not sessions:
        raise HTTPException(status_code=404, detail="No data found")

    total_time = sum(s.viewing_time for s in sessions)
    if total_time == 0:
        return {"message": "Total viewing time is zero, no meaningful scores available."}

    weighted_scores = {
        "sentiment": 0,
        "emotions": {},
        "political_bias": {},
        "stereotype": {}  
    }

    for session in sessions:
        weight = session.viewing_time / total_time
        weighted_scores["sentiment"] += session.sentiment_score * weight

        for category, target_key in [("emotions", "emotions"), ("political_bias", "political_bias"), ("stereotype_score", "stereotype")]:
            session_data = getattr(session, category)
            if not session_data:
                continue

            for key, score in session_data.items():
                if key not in weighted_scores[target_key]:
                    weighted_scores[target_key][key] = 0
                weighted_scores[target_key][key] += score * weight


    weighted_scores["sentiment"] = round(weighted_scores["sentiment"], 4)
    weighted_scores["emotions"] = {k: round(v, 4) for k, v in weighted_scores["emotions"].items()}
    weighted_scores["political_bias"] = {k: round(v, 4) for k, v in weighted_scores["political_bias"].items()}
    weighted_scores["stereotype"] = {k: round(v, 4) for k, v in weighted_scores["stereotype"].items()}  # ✅ Fixed access to correct key

    return {
        "website": website if website else "All websites",
        "total_viewing_time": round(total_time, 4),
        "weighted_scores": weighted_scores
    }

@app.get("/most_frequent_label")
def get_labels_info(db: Session = Depends(get_db)):
    all_label_counts = (
        db.query(
            WebsiteClassification.label,
            func.count(WebsiteClassification.id).label("count")
        )
        .group_by(WebsiteClassification.label)
        .order_by(func.count(WebsiteClassification.id).desc())
        .all()
    )

    if not all_label_counts:
         raise HTTPException(status_code=404, detail="No classification records found.")

    total = db.query(func.count(WebsiteClassification.id)).scalar()

    top = all_label_counts[0]
    top_label_result = {
        "label": top.label,
        "count": top.count,
        "percentage": (top.count / total * 100) if total > 0 else 0,
        "message": label_messages.get(top.label, "")
    }

    all_percentages = []
    for item in all_label_counts:
         all_percentages.append({
             "label": item.label,
             "count": item.count,
             "percentage": (item.count / total * 100) if total > 0 else 0,
         })

    return {"top_labels": [top_label_result], "all_percentages": all_percentages}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))