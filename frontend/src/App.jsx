import React, { useState, useEffect } from 'react';
import { FaUtensils, FaPlus, FaList, FaScissors } from 'react-icons/fa';
import axios from 'axios';

function App() {
  const [url, setUrl] = useState('');
  const [recipes, setRecipes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [scrapedRecipes, setScrapedRecipes] = useState([]);
  const [activeTab, setActiveTab] = useState('scrape');

  // API endpoint - uses Vite proxy in dev
  const API_URL = '/api/v1';

  // Load saved recipes on mount
  useEffect(() => {
    const loadRecipes = async () => {
      try {
        const response = await axios.get(`${API_URL}/recipes`);
        setRecipes(response.data);
      } catch (error) {
        console.error('Error loading recipes:', error);
      }
    };
    loadRecipes();
  }, []);

  const handleScrape = async () => {
    if (!url) {
      alert('Please enter a URL');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(`${API_URL}/scrape`, { url });
      setScrapedRecipes([response.data.recipe, ...scrapedRecipes]);
      setRecipes([response.data.recipe, ...recipes]);
      alert('Recipe scraped successfully!');
      setUrl('');
    } catch (error) {
      console.error('Error scraping:', error);
      alert('Failed to scrape recipe. Make sure backend is running and URL is valid.');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveToRecipes = async (recipe) => {
    try {
      await axios.post(`${API_URL}/recipes`, {
        title: recipe.title,
        url: recipe.url,
        summary: recipe.summary,
        ingredients: Array.isArray(recipe.ingredients) ? recipe.ingredients : [],
        instructions: Array.isArray(recipe.instructions) ? recipe.instructions : [],
        prep_time: recipe.prep_time,
        cook_time: recipe.cook_time,
        servings: recipe.servings,
        difficulty: recipe.difficulty,
        category: recipe.category
      });
      alert('Recipe saved successfully!');
    } catch (error) {
      console.error('Error saving recipe:', error);
      alert('Failed to save recipe to database.');
    }
  };

  const handleGetRecipes = async () => {
    try {
      const response = await axios.get(`${API_URL}/recipes`);
      setRecipes(response.data);
    } catch (error) {
      console.error('Error getting recipes:', error);
    }
  };

  const handleGetScraped = async () => {
    try {
      const response = await axios.get(`${API_URL}/scrape`);
      setScrapedRecipes(response.data);
    } catch (error) {
      console.error('Error getting scraped recipes:', error);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <h1>
          <FaUtensils /> Ricette App
        </h1>
      </header>

      <nav className="nav">
        <button
          className={activeTab === 'scrape' ? 'active' : ''}
          onClick={() => setActiveTab('scrape')}
        >
          <FaScissors /> Scrape Recipe
        </button>
        <button
          className={activeTab === 'recipes' ? 'active' : ''}
          onClick={() => setActiveTab('recipes')}
        >
          <FaList /> Saved Recipes
        </button>
      </nav>

      <main className="main">
        {activeTab === 'scrape' && (
          <div className="scrape-section">
            <div className="scrape-form">
              <h2>Scrape from URL</h2>
              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="Enter recipe URL..."
                disabled={loading}
              />
              <button onClick={handleScrape} disabled={loading}>
                {loading ? 'Scraping...' : <><FaPlus /> Scrape Recipe</>}
              </button>
            </div>

            {scrapedRecipes.length > 0 && (
              <div className="scraped-list">
                <h3>Scraped Recipes</h3>
                {scrapedRecipes.map((recipe, index) => (
                  <div key={index} className="recipe-card">
                    <h4>{recipe.title}</h4>
                    {recipe.category && <span className="badge">{recipe.category}</span>}
                    {recipe.difficulty && <span className="badge">{recipe.difficulty}</span>}
                    <div className="recipe-meta">
                      {recipe.prep_time && <span>Prep: {recipe.prep_time} min</span>}
                      {recipe.cook_time && <span>Cook: {recipe.cook_time} min</span>}
                      {recipe.servings && <span>Servings: {recipe.servings}</span>}
                    </div>
                    <div className="recipe-actions">
                      <button onClick={() => handleSaveToRecipes(recipe)}>
                        <FaPlus /> Save to Recipes
                      </button>
                      <a
                        href={recipe.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="view-link"
                      >
                        View Original
                      </a>
                    </div>
                    <div className="recipe-details">
                      <h5>Ingredients</h5>
                      <ul>
                        {(recipe.ingredients || []).slice(0, 5).map((ing, i) => (
                          <li key={i}>{ing}</li>
                        ))}
                      </ul>
                      <h5>Instructions</h5>
                      <ol>
                        {(recipe.instructions || []).slice(0, 5).map((inst, i) => (
                          <li key={i}>{inst}</li>
                        ))}
                      </ol>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'recipes' && (
          <div className="recipes-section">
            <button onClick={handleGetRecipes}>
              <FaList /> Load Saved Recipes
            </button>
            <div className="recipes-list">
              {recipes.length > 0 ? (
                recipes.map((recipe) => (
                  <div key={recipe.id} className="recipe-card">
                    <h4>{recipe.title}</h4>
                    {recipe.category && <span className="badge">{recipe.category}</span>}
                    {recipe.difficulty && <span className="badge">{recipe.difficulty}</span>}
                    <div className="recipe-meta">
                      {recipe.prep_time && <span>Prep: {recipe.prep_time} min</span>}
                      {recipe.cook_time && <span>Cook: {recipe.cook_time} min</span>}
                      {recipe.servings && <span>Servings: {recipe.servings}</span>}
                    </div>
                    <div className="recipe-details">
                      <h5>Ingredients</h5>
                      <ul>
                        {(recipe.ingredients || []).slice(0, 5).map((ing, i) => (
                          <li key={i}>{ing}</li>
                        ))}
                      </ul>
                      <h5>Instructions</h5>
                      <ol>
                        {(recipe.instructions || []).slice(0, 5).map((inst, i) => (
                          <li key={i}>{inst}</li>
                        ))}
                      </ol>
                    </div>
                    <a
                      href={recipe.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="view-link"
                    >
                      View Original
                    </a>
                  </div>
                ))
              ) : (
                <p>No saved recipes yet. Scrape some recipes first!</p>
              )}
            </div>
          </div>
        )}
      </main>

      <style>{`
        .app {
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
          max-width: 1200px;
          margin: 0 auto;
          padding: 20px;
        }
        .header {
          text-align: center;
          margin-bottom: 30px;
        }
        .header h1 {
          color: #333;
          font-size: 2.5rem;
        }
        .header h1 svg {
          color: #e67e22;
          margin-right: 10px;
        }
        .nav {
          display: flex;
          justify-content: center;
          gap: 20px;
          margin-bottom: 30px;
        }
        .nav button {
          padding: 10px 20px;
          font-size: 1rem;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          background: #f0f0f0;
          transition: all 0.3s;
        }
        .nav button.active {
          background: #e67e22;
          color: white;
        }
        .nav button svg {
          margin-right: 8px;
        }
        .main {
          min-height: 500px;
        }
        .scrape-section,
        .recipes-section {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .scrape-form {
          background: #fff;
          padding: 30px;
          border-radius: 12px;
          box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .scrape-form h2 {
          margin-top: 0;
          color: #333;
        }
        .scrape-form input {
          width: 100%;
          padding: 12px;
          font-size: 1rem;
          border: 1px solid #ddd;
          border-radius: 6px;
          margin-bottom: 15px;
        }
        .scrape-form button {
          width: 100%;
          padding: 12px;
          font-size: 1rem;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          background: #27ae60;
          color: white;
          transition: background 0.3s;
        }
        .scrape-form button:hover {
          background: #219a52;
        }
        .scrape-form button:disabled {
          background: #ccc;
        }
        .scraped-list,
        .recipes-list {
          display: grid;
          gap: 20px;
        }
        .recipe-card {
          background: #fff;
          padding: 20px;
          border-radius: 12px;
          box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .recipe-card h4 {
          margin-top: 0;
          color: #333;
        }
        .badge {
          display: inline-block;
          padding: 4px 10px;
          margin: 5px 5px 5px 0;
          background: #e67e22;
          color: white;
          border-radius: 15px;
          font-size: 0.8rem;
        }
        .recipe-meta {
          display: flex;
          gap: 15px;
          margin: 10px 0;
          color: #666;
        }
        .recipe-actions {
          display: flex;
          gap: 10px;
          margin: 15px 0;
        }
        .recipe-actions button,
        .view-link {
          padding: 8px 16px;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          font-size: 0.9rem;
        }
        .recipe-actions button {
          background: #27ae60;
          color: white;
        }
        .recipe-actions button:hover {
          background: #219a52;
        }
        .view-link {
          background: transparent;
          color: #3498db;
          text-decoration: none;
        }
        .view-link:hover {
          text-decoration: underline;
        }
        .recipe-details {
          margin-top: 15px;
          padding-top: 15px;
          border-top: 1px solid #eee;
        }
        .recipe-details h5 {
          margin: 10px 0 5px;
          color: #333;
        }
        .recipe-details ul,
        .recipe-details ol {
          margin: 0;
          padding-left: 20px;
        }
        .recipe-details li {
          margin: 5px 0;
        }
        @media (max-width: 768px) {
          .app {
            padding: 10px;
          }
          .header h1 {
            font-size: 1.8rem;
          }
          .recipe-actions {
            flex-direction: column;
          }
        }
      `}</style>
    </div>
  );
}

export default App;